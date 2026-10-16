"""Persistent normalized candle cache; bounded imports and indexed range reuse."""
from contextlib import contextmanager
import csv
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import time
import uuid
import zipfile

from .common import INTERVALS,canonical,decimal,digest,identifier,symbol,timestamp
from .data import FIELDS,MAX_ROWS
from .errors import ResourceLimit,ValidationError

CHUNK=500
MAX_IMPORT_BYTES=24*1024*1024
MAX_EXPANDED_BYTES=64*1024*1024
MAX_IMPORT_ROWS=700_000


def now():return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def identity(raw):
    if not isinstance(raw,dict) or set(raw)-{"exchange","market","symbol","interval","synthetic","source","retrieved_at"}:
        raise ValidationError("invalid data-source fields")
    exchange=raw.get("exchange")
    if exchange not in ("BINANCE","SYNTHETIC") or raw.get("market") not in ("SPOT","USDT_LINEAR_PERPETUAL") or raw.get("interval") not in INTERVALS:
        raise ValidationError("explicit supported exchange, market and interval required")
    if type(raw.get("synthetic")) is not bool or (exchange=="SYNTHETIC")!=raw["synthetic"]:
        raise ValidationError("explicit truthful synthetic/exchange classification required")
    source=raw.get("source")
    if not isinstance(source,str) or not 1<=len(source)<=500:raise ValidationError("source attribution required (up to500 characters)")
    retrieved=raw.get("retrieved_at")
    if retrieved is not None:timestamp(retrieved)
    return dict(exchange=exchange,market=raw["market"],symbol=symbol(raw.get("symbol")),interval=raw["interval"],synthetic=raw["synthetic"],source=source,retrieved_at=retrieved)


def key(meta):return digest([meta[k] for k in ("exchange","market","symbol","interval","synthetic")])
def group_key(meta):return "cache_"+digest([meta[k] for k in ("exchange","market","interval","synthetic")])[:40]


def normalize_time(value):
    if isinstance(value,str) and value.isascii() and value.isdigit():value=int(value)
    if isinstance(value,int) and value>=10**14:
        if value%1000:raise ValidationError("microsecond open timestamp is not millisecond aligned")
        value//=1000
    return timestamp(value)


def numeric_text(value):
    # Canonical VALUE without rounding: CSV/API trailing-zero formatting is not
    # a changed price. Decimal.normalize() could round at the ambient precision.
    text=format(value,"f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def parse_rows(stream,meta):
    step=INTERVALS[meta["interval"]];previous=None;count=0
    reader=csv.reader(io.TextIOWrapper(stream,encoding="utf-8-sig",newline=""),strict=True)
    first=True
    try:
        for row in reader:
            if first and row and row[0] in ("open_time","open_time_ms"):
                if len(row) not in (6,12):raise ValidationError("unsupported CSV header")
                if tuple(row[:6])!=FIELDS:raise ValidationError("CSV column order must be open_time,open,high,low,close,volume")
                first=False;continue
            first=False
            if len(row) not in (6,12):raise ValidationError("CSV must contain normalized6 or native Binance12 columns")
            count+=1
            if count>MAX_IMPORT_ROWS:raise ResourceLimit("700,000-row import bound reached")
            ts=normalize_time(row[0])
            if ts%step or ts+step>int(time.time()*1000):raise ValidationError("misaligned, incomplete or future candle")
            if previous is not None and ts!=previous+step:
                raise ValidationError("duplicate/out-of-order candle or gap inside import; split genuine continuous segments and fill missing ranges explicitly")
            previous=ts
            o,h,lo,c=(decimal(x,"price",".000000000001") for x in row[1:5]);v=decimal(row[5],"volume",0)
            if h<max(o,c) or lo>min(o,c) or h<lo:raise ValidationError("invalid OHLC")
            if len(row)==12:
                close=int(row[6]);close=close//1000 if close>=10**14 else close
                if close!=ts+step-1:raise ValidationError("native close timestamp mismatch")
                for x in (row[7],row[9],row[10]):decimal(x,"native volume",0)
                if not row[8].isdigit():raise ValidationError("invalid native trade count")
            yield ts,canonical([numeric_text(x) for x in (o,h,lo,c,v)])
    except (csv.Error,UnicodeError,ValueError) as exc:
        if isinstance(exc,ValidationError):raise
        raise ValidationError("invalid CSV encoding, timestamp or numeric data") from None
    if not count:raise ValidationError("empty candle file")


class HistoricalCache:
    def __init__(self,store):
        self.store=store
        with store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            for sql in [
                "CREATE TABLE IF NOT EXISTS cache_series(id TEXT PRIMARY KEY,group_id TEXT NOT NULL,meta TEXT NOT NULL)",
                "CREATE INDEX IF NOT EXISTS cache_group_idx ON cache_series(group_id)",
                "CREATE TABLE IF NOT EXISTS cache_candles(series_id TEXT NOT NULL,open_ms BIGINT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(series_id,open_ms))",
                "CREATE TABLE IF NOT EXISTS cache_imports(id TEXT PRIMARY KEY,series_id TEXT NOT NULL,status TEXT NOT NULL,source_hash TEXT NOT NULL,started TEXT NOT NULL,finished TEXT,records INTEGER NOT NULL DEFAULT 0,inserted INTEGER NOT NULL DEFAULT 0,error TEXT,meta TEXT NOT NULL)",
                "CREATE UNIQUE INDEX IF NOT EXISTS cache_one_import ON cache_imports(series_id) WHERE status='RUNNING'",
                "CREATE TABLE IF NOT EXISTS cache_staging(import_id TEXT NOT NULL,open_ms BIGINT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(import_id,open_ms))",
                "CREATE TABLE IF NOT EXISTS cache_operations(series_id TEXT PRIMARY KEY,token TEXT NOT NULL,kind TEXT NOT NULL,started TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS cache_fetch_receipts(id TEXT PRIMARY KEY,series_id TEXT NOT NULL,url TEXT NOT NULL,retrieved_at TEXT NOT NULL,body_hash TEXT NOT NULL,body TEXT NOT NULL)",
            ]:c.execute(sql)

    @contextmanager
    def operation(self,metadata,kind):
        meta=identity(metadata);sid=key(meta);token=uuid.uuid4().hex
        import sqlite3
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:c.execute("INSERT INTO cache_operations VALUES(?,?,?,?)",(sid,token,kind,now()))
            except sqlite3.IntegrityError:raise ResourceLimit("another import/download owns this series; interrupted operations need explicit recovery") from None
        try:yield token
        finally:
            with self.store.connect() as c:c.execute("DELETE FROM cache_operations WHERE series_id=? AND token=?",(sid,token))

    def series(self,series_id):
        identifier(series_id)
        with self.store.connect() as c:r=c.execute("SELECT meta FROM cache_series WHERE id=?",(series_id,)).fetchone()
        if r is None:raise ValidationError("unknown cached series")
        return json.loads(r[0])

    def missing(self,meta,start,end):
        meta=identity(meta);start=timestamp(start);end=timestamp(end);step=INTERVALS[meta["interval"]]
        if start>=end or start%step or end%step:raise ValidationError("invalid aligned cache range")
        if end-start>366*86400000:raise ResourceLimit("plan no more than366days per request")
        missing=[];cursor=start
        with self.store.connect() as c:
            rows=c.execute("SELECT open_ms FROM cache_candles WHERE series_id=? AND open_ms>=? AND open_ms<? ORDER BY open_ms",(key(meta),start,end))
            while True:
                batch=rows.fetchmany(CHUNK)
                if not batch:break
                for r in batch:
                    ts=r[0]
                    if ts>cursor:missing.append({"start_ms":cursor,"end_ms":ts,"candles":(ts-cursor)//step})
                    cursor=ts+step
        if cursor<end:missing.append({"start_ms":cursor,"end_ms":end,"candles":(end-cursor)//step})
        return missing

    def ingest(self,file,filename,metadata,checksum=None,operation_token=None):
        if operation_token is None:
            with self.operation(metadata,"IMPORT") as token:
                return self._ingest(file,filename,metadata,checksum)
        with self.store.connect() as c:
            row=c.execute("SELECT token FROM cache_operations WHERE series_id=?",(key(identity(metadata)),)).fetchone()
            if row is None or row[0]!=operation_token:raise ValidationError("invalid internal cache-operation ownership")
        return self._ingest(file,filename,metadata,checksum)

    def _ingest(self,file,filename,metadata,checksum=None):
        meta=identity(metadata);sid=key(meta);import_id="imp_"+uuid.uuid4().hex
        file.seek(0,2);size=file.tell();file.seek(0)
        if size>MAX_IMPORT_BYTES:raise ResourceLimit("24MiB upload-file limit exceeded")
        sha=hashlib.sha256()
        while True:
            block=file.read(65536)
            if not block:break
            sha.update(block)
        source_hash=sha.hexdigest();file.seek(0)
        if checksum is not None:
            fields=checksum.strip().split()
            if not fields or fields[0].lower()!=source_hash:raise ValidationError("source SHA-256/CHECKSUM mismatch")
            if len(fields)>1 and Path(fields[1].lstrip("*")).name!=filename:raise ValidationError("CHECKSUM filename mismatch")
        if not isinstance(filename,str) or Path(filename).name!=filename or "\\" in filename or len(filename)>120:raise ValidationError("unsafe source filename")
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:c.execute("INSERT INTO cache_imports(id,series_id,status,source_hash,started,meta) VALUES(?,?,'RUNNING',?,?,?)",(import_id,sid,source_hash,now(),canonical(meta|{"checksum_verified":checksum is not None,"source_file":filename})))
            except Exception as exc:
                import sqlite3
                if isinstance(exc,sqlite3.IntegrityError):raise ResourceLimit("overlapping import/download already running for this exact series") from None
                raise
        archive=None;stream=None;rows=0;first_ts=None;last_ts=None
        try:
            if filename.lower().endswith(".zip"):
                archive=zipfile.ZipFile(file)
                items=archive.infolist()
                if len(items)!=1 or items[0].is_dir() or "\\" in items[0].filename or Path(items[0].filename).name!=items[0].filename or not items[0].filename.endswith(".csv"):
                    raise ValidationError("ZIP must contain exactly one plain CSV; no directories or traversal")
                item=items[0]
                if item.file_size>MAX_EXPANDED_BYTES or item.file_size>max(1,item.compress_size)*250:
                    raise ResourceLimit("ZIP expansion bound exceeded")
                # Native Binance filenames bind source symbol/timeframe, not hidden substitution.
                if "-" in item.filename:
                    prefix=f"{meta['symbol']}-{meta['interval']}-"
                    if not item.filename.startswith(prefix):raise ValidationError("archive symbol/timeframe does not match declared identity")
                stream=archive.open(item)
            elif filename.lower().endswith(".csv"):stream=file
            else:raise ValidationError("only CSV or single-CSV ZIP supported")
            batch=[]
            for ts,data in parse_rows(stream,meta):
                if first_ts is None:first_ts=ts
                last_ts=ts
                batch.append((import_id,ts,data));rows+=1
                if len(batch)==CHUNK:self._stage(batch,import_id,rows);batch=[]
            if batch:self._stage(batch,import_id,rows)
            with self.store.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                conflicts=c.execute("SELECT COUNT(*) FROM cache_staging s JOIN cache_candles c ON c.series_id=? AND c.open_ms=s.open_ms WHERE s.import_id=? AND c.data<>s.data",(sid,import_id)).fetchone()[0]
                if conflicts:raise ValidationError("existing candle conflict; immutable stored prices were NOT overwritten")
                c.execute("INSERT INTO cache_series(id,group_id,meta) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",(sid,group_key(meta),canonical(meta)))
                before=c.execute("SELECT COUNT(*) FROM cache_candles WHERE series_id=?",(sid,)).fetchone()[0]
                c.execute("INSERT INTO cache_candles(series_id,open_ms,data) SELECT ?,open_ms,data FROM cache_staging WHERE import_id=? ON CONFLICT(series_id,open_ms) DO NOTHING",(sid,import_id))
                after=c.execute("SELECT COUNT(*) FROM cache_candles WHERE series_id=?",(sid,)).fetchone()[0]
                c.execute("UPDATE cache_imports SET status='COMPLETE',finished=?,records=?,inserted=? WHERE id=?",(now(),rows,after-before,import_id))
                c.execute("UPDATE cache_imports SET meta=? WHERE id=?",(canonical(meta|{"checksum_verified":checksum is not None,"source_file":filename,"first_open_ms":first_ts,"last_complete_ms":last_ts+INTERVALS[meta["interval"]]}),import_id))
                c.execute("DELETE FROM cache_staging WHERE import_id=?",(import_id,))
            return {"id":import_id,"series_id":sid,"status":"COMPLETE","records":rows,"inserted":after-before,"reused":rows-(after-before),"source_sha256":source_hash,"checksum_verified":checksum is not None}
        except Exception as exc:
            message=str(exc) if isinstance(exc,ValidationError) else "invalid archive or interrupted import; no candles committed"
            with self.store.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                c.execute("UPDATE cache_imports SET status='FAILED',finished=?,error=? WHERE id=?",(now(),message,import_id))
                c.execute("DELETE FROM cache_staging WHERE import_id=?",(import_id,))
            if isinstance(exc,ValidationError):raise
            raise ValidationError(message) from None
        finally:
            if stream is not None and stream is not file:stream.close()
            if archive is not None:archive.close()

    def _stage(self,batch,import_id,rows):
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if hasattr(c,"executemany"):c.executemany("INSERT INTO cache_staging VALUES(?,?,?)",batch)
            else:
                for record in batch:c.execute("INSERT INTO cache_staging VALUES(?,?,?)",record)
            c.execute("UPDATE cache_imports SET records=? WHERE id=?",(rows,import_id))

    def inventory(self,query=""):
        if not isinstance(query,str) or len(query)>100:raise ValidationError("invalid inventory search")
        with self.store.connect() as c:
            values=c.execute("SELECT s.id,s.group_id,s.meta,COUNT(c.open_ms) AS records,MIN(c.open_ms) AS first_ms,MAX(c.open_ms) AS last_ms FROM cache_series s LEFT JOIN cache_candles c ON c.series_id=s.id GROUP BY s.id,s.group_id,s.meta ORDER BY s.id").fetchall()
            imports=[]
            for r in c.execute("SELECT id,series_id,status,started,finished,records,inserted,error,source_hash,meta FROM cache_imports ORDER BY started DESC LIMIT 100"):
                value=dict(r);value["source"]=json.loads(value.pop("meta"));imports.append(value)
        result=[]
        for r in values:
            m=json.loads(r["meta"])
            if query.lower() not in canonical(m).lower():continue
            step=INTERVALS[m["interval"]];expected=(r["last_ms"]-r["first_ms"])//step+1 if r["records"] else 0
            result.append({**m,"id":r["id"],"group_id":r["group_id"],"records":r["records"],"first_open_ms":r["first_ms"],"last_complete_ms":r["last_ms"]+step if r["records"] else None,"missing_intervals":expected-r["records"],"coverage_complete":expected==r["records"]})
        return {"series":result,"imports":imports,"backend":self.store.backend,"durable_backend_configured":self.store.durable}

    def recover_interrupted(self):
        """Owner CLI only after every importer/downloader/worker is stopped."""
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("UPDATE cache_imports SET status='INTERRUPTED',error='Explicit owner recovery after stopped workers' WHERE status='RUNNING'")
            c.execute("DELETE FROM cache_staging")
            c.execute("DELETE FROM cache_operations")

    def groups(self):
        groups={}
        for s in self.inventory()["series"]:
            g=groups.setdefault(s["group_id"],{"id":s["group_id"],"exchange":s["exchange"],"market":s["market"],"interval":s["interval"],"synthetic":s["synthetic"],"coverage":[],"warnings":["Persistent cache; current exchange eligibility/filters and original retrieval receipts may remain unverified."]})
            g["coverage"].append({"symbol":s["symbol"],"candles":s["records"],"first_open_ms":s["first_open_ms"],"last_complete_ms":s["last_complete_ms"],"missing_intervals":s["missing_intervals"]})
        return list(groups.values())

    def export_bundle(self,group,symbols,start,end,warmup,target):
        started=time.monotonic()
        identifier(group);available={s["symbol"]:s for s in self.inventory()["series"] if s["group_id"]==group}
        if not symbols or len(symbols)!=len(set(symbols)) or set(symbols)-available.keys():raise ValidationError("select distinct symbols present in this cache group")
        first=next(iter(available.values()));step=INTERVALS[first["interval"]];start=timestamp(start)-warmup*step;end=timestamp(end)
        if len(symbols)*((end-start)//step)>MAX_ROWS:raise ResourceLimit("selected range plus warm-up exceeds200,000 replay candles; select fewer symbols/shorter range, never silently truncate")
        target=Path(target);target.mkdir(parents=True,exist_ok=True);files=[]
        for sym in sorted(symbols):
            meta={k:available[sym][k] for k in ("exchange","market","symbol","interval","synthetic","source","retrieved_at")}
            missing=self.missing(meta,start,end)
            if missing:raise ValidationError(f"{sym}: cached history/warm-up incomplete; missing {sum(x['candles'] for x in missing)} candles. Use missing-range plan to supply gaps.")
            p=target/(sym+".csv")
            with p.open("w",newline="") as f,self.store.connect() as c:
                w=csv.writer(f);w.writerow(FIELDS)
                rows=c.execute("SELECT open_ms,data FROM cache_candles WHERE series_id=? AND open_ms>=? AND open_ms<? ORDER BY open_ms",(available[sym]["id"],start,end))
                while True:
                    if time.monotonic()-started>20:raise ResourceLimit("20-second cache export budget exceeded; no shortened dataset accepted")
                    batch=rows.fetchmany(CHUNK)
                    if not batch:break
                    for row in batch:w.writerow([row[0],*json.loads(row[1])])
            files.append({"symbol":sym,"file":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
        manifest={"schema_version":1,"dataset_id":group,"exchange":first["exchange"],"market":first["market"],"interval":first["interval"],"synthetic":first["synthetic"],"source":"Reused normalized immutable candle cache; identity and receipts available in Historical Data Manager","retrieved_at":None,"files":files}
        (target/"manifest.json").write_text(canonical(manifest));return target
