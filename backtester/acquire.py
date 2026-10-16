"""Bounded official public Binance klines; fetch only genuinely missing ranges."""
import csv
import hashlib
import io
import json
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler
import uuid

from .cache import identity,key,now
from .common import INTERVALS,canonical,timestamp
from .errors import ValidationError,ResourceLimit


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise HTTPError(req.full_url,code,"Redirect refused; source identity must remain explicit",headers,fp)


def public_open(request,timeout):return build_opener(NoRedirect()).open(request,timeout=timeout)


def fetch_missing(cache,metadata,start,end,*,opener=public_open,sleep=time.sleep):
    meta=identity(metadata)
    if meta["synthetic"]:raise ValidationError("online collection never creates synthetic substitutes")
    start=timestamp(start);end=timestamp(end);step=INTERVALS[meta["interval"]]
    requests=0;received=0;imports=[];started=time.monotonic()
    with cache.operation(meta,"DOWNLOAD") as token:
        missing=cache.missing(meta,start,end)
        for gap in missing:
            cursor=gap["start_ms"]
            while cursor<gap["end_ms"]:
                if requests>=8 or time.monotonic()-started>=45:
                    remaining=cache.missing(meta,start,end)
                    return {"status":"PARTIAL","requests":requests,"bytes":received,"imports":imports,"remaining":remaining,"message":"8-request/45-second batch bound reached; repeat to fetch remaining ranges only"}
                count=min(1000,(gap["end_ms"]-cursor)//step)
                base="https://api.binance.com/api/v3/klines" if meta["market"]=="SPOT" else "https://fapi.binance.com/fapi/v1/klines"
                url=base+"?"+urlencode({"symbol":meta["symbol"],"interval":meta["interval"],"startTime":cursor,"endTime":cursor+count*step-1,"limit":count})
                requests+=1
                try:
                    with opener(Request(url,headers={"User-Agent":"HKS-History-Cache/2"}),timeout=8) as response:
                        # Bound actual bytes, not just a possibly false Content-Length.
                        raw=response.read(min(2*1024*1024,16*1024*1024-received)+1)
                except HTTPError as exc:
                    raise ValidationError(f"official public source returned HTTP {exc.code}; no retry or alternate-market fallback; existing cached pages retained") from None
                except (URLError,TimeoutError,OSError):
                    raise ValidationError("public source unavailable/network denied; no retry; import owner-supplied CSV/ZIP instead") from None
                received+=len(raw)
                if len(raw)>2*1024*1024 or received>16*1024*1024:raise ResourceLimit("historical download byte cap reached; completed prior pages retained")
                try:data=json.loads(raw)
                except ValueError:raise ValidationError("public source returned invalid JSON") from None
                if not isinstance(data,list) or len(data)>count:raise ValidationError("invalid public kline response")
                if not data:
                    return {"status":"INCOMPLETE","requests":requests,"bytes":received,"imports":imports,"remaining":cache.missing(meta,start,end),"message":"No source history available; no candles fabricated"}
                for i,row in enumerate(data):
                    if not isinstance(row,list) or len(row)!=12 or row[0]!=cursor+i*step:
                        raise ValidationError("public response has gaps, duplicates, unexpected interval or range")
                stream=io.StringIO(newline="");writer=csv.writer(stream);writer.writerows(data)
                localmeta=meta|{"source":base,"retrieved_at":now()}
                result=cache.ingest(io.BytesIO(stream.getvalue().encode()),meta["symbol"]+".csv",localmeta,operation_token=token)
                imports.append(result)
                with cache.store.connect() as c:
                    c.execute("INSERT INTO cache_fetch_receipts VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,key(meta),url,now(),hashlib.sha256(raw).hexdigest(),raw.decode()))
                cursor+=len(data)*step
                if len(data)<count:
                    return {"status":"INCOMPLETE","requests":requests,"bytes":received,"imports":imports,"remaining":cache.missing(meta,start,end),"message":"Source returned shorter history than requested"}
                if requests<8:sleep(1)
        return {"status":"COMPLETE","requests":requests,"bytes":received,"imports":imports,"remaining":cache.missing(meta,start,end)}
