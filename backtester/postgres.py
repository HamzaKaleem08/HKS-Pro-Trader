"""Durable PostgreSQL adapter; no runtime-filesystem durability assumptions."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime,timezone
from urllib.parse import parse_qs,urlsplit

from .errors import ValidationError
from .storage import Store


class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)


class Cursor:
    def __init__(self,cursor):self.raw=cursor
    @property
    def rowcount(self):return self.raw.rowcount
    def fetchone(self):
        row=self.raw.fetchone();return None if row is None else Row(row)
    def fetchall(self):return [Row(x) for x in self.raw.fetchall()]
    def fetchmany(self,size=500):return [Row(x) for x in self.raw.fetchmany(size)]
    def __iter__(self):
        for row in self.raw:yield Row(row)


class Connection:
    def __init__(self,raw):self.raw=raw
    def execute(self,sql,args=()):
        if sql=="BEGIN IMMEDIATE":sql="SELECT pg_advisory_xact_lock(634719204)"
        if sql.startswith("INSERT OR IGNORE INTO"):
            sql=sql.replace("INSERT OR IGNORE INTO","INSERT INTO",1)+" ON CONFLICT DO NOTHING"
        import psycopg
        try:
            if sql.startswith(("SELECT open_ms FROM cache_candles","SELECT open_ms,data FROM cache_candles")):
                cursor=self.raw.cursor(name="history_"+uuid.uuid4().hex)
                cursor.execute(sql.replace("?","%s"),args)
                return Cursor(cursor)
            return Cursor(self.raw.execute(sql.replace("?","%s"),args))
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError("persistent constraint violation") from None
    def executemany(self,sql,rows):
        cur=self.raw.cursor();cur.executemany(sql.replace("?","%s"),rows);return Cursor(cur)


class PostgresStore(Store):
    backend="postgresql"
    durable=True
    def __init__(self,url,state_dir,*,allow_local_plaintext=False):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise ValidationError("psycopg[binary] dependency is required for persistent PostgreSQL") from None
        parsed=urlsplit(url)
        if parsed.scheme not in ("postgres","postgresql") or not parsed.hostname:
            raise ValidationError("valid PostgreSQL DATABASE_URL required")
        mode=parse_qs(parsed.query).get("sslmode",["require"])[0]
        if mode not in ("require","verify-ca","verify-full") and not (allow_local_plaintext and parsed.hostname in ("localhost","127.0.0.1")):
            raise ValidationError("PostgreSQL must use TLS; plaintext is allowed only for explicitly disposable loopback tests")
        self.url=url;self.root=Path(state_dir).resolve();self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.root/"no-local-database-used"
        self._sslmode=mode;self._dict_row=dict_row
        with self.connect(initialize=True) as c:
            c.execute("SELECT pg_advisory_xact_lock(634719204)")
            for sql in [
                "CREATE SCHEMA IF NOT EXISTS hks_backtester",
                "SET LOCAL search_path TO hks_backtester",
                "CREATE TABLE IF NOT EXISTS strategies(version_id TEXT PRIMARY KEY,content_hash TEXT NOT NULL UNIQUE,definition TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT NOT NULL,error TEXT,result TEXT,created_order BIGSERIAL)",
                "CREATE UNIQUE INDEX IF NOT EXISTS one_running_job ON jobs(status) WHERE status='RUNNING'",
                "CREATE OR REPLACE FUNCTION immutable_record() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable record'; END $$",
                "DROP TRIGGER IF EXISTS strategies_no_mutation ON strategies",
                "CREATE TRIGGER strategies_no_mutation BEFORE UPDATE OR DELETE ON strategies FOR EACH ROW EXECUTE FUNCTION immutable_record()",
                "DROP TRIGGER IF EXISTS completed_no_mutation ON jobs",
                "CREATE TRIGGER completed_no_mutation BEFORE UPDATE OR DELETE ON jobs FOR EACH ROW WHEN (OLD.status='COMPLETE') EXECUTE FUNCTION immutable_record()",
                "CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY)",
                "INSERT INTO schema_version VALUES(2) ON CONFLICT DO NOTHING",
            ]:c.execute(sql)

    @contextmanager
    def connect(self,initialize=False):
        import psycopg
        try:
            conn=psycopg.connect(self.url,connect_timeout=5,sslmode=self._sslmode,row_factory=self._dict_row)
        except psycopg.Error:
            raise ValidationError("Persistent PostgreSQL connection failed; check the secure DATABASE_URL and network/TLS settings") from None
        try:
            conn.execute("SET LOCAL statement_timeout='15000ms'")
            conn.execute("SET LOCAL lock_timeout='3000ms'")
            if not initialize:conn.execute("SET LOCAL search_path TO hks_backtester")
            yield Connection(conn);conn.commit()
        except BaseException:
            conn.rollback();raise
        finally:conn.close()

    def begin_job(self,with_progress=False):
        import uuid
        from .errors import ResourceLimit
        job="run_"+uuid.uuid4().hex
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                c.execute("INSERT INTO jobs(id,status) VALUES(?,'RUNNING')",(job,))
                if with_progress:c.execute("INSERT INTO job_progress VALUES(?,0,'ADMITTED',?)",(job,datetime.now(timezone.utc).isoformat(timespec="milliseconds")))
            except sqlite3.IntegrityError:
                raise ResourceLimit("another job is running; interrupted jobs require explicit recovery") from None
        return job

    def list_jobs(self):
        with self.connect() as c:return [dict(r) for r in c.execute("SELECT id,status,error FROM jobs ORDER BY created_order DESC LIMIT 200")]
