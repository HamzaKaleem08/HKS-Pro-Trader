"""Separate disposable research state, never legacy wallet.json/SQLite wallets."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime,timezone

from .common import canonical, digest, identifier
from .errors import ResourceLimit, ValidationError
from .strategies import build_strategy, validate_definition

MAX_RESULT_BYTES = 16 * 1024 * 1024


class Store:
    backend="sqlite"
    durable=False
    def __init__(self, state_dir):
        self.root = Path(state_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "backtester-research.sqlite3"
        if self.path.is_symlink():
            raise ValidationError("unsafe state database")
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValidationError("unsupported research schema version")
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS strategies(version_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE, definition TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS strategies_no_update BEFORE UPDATE ON strategies BEGIN SELECT RAISE(ABORT, 'immutable version'); END;
                CREATE TRIGGER IF NOT EXISTS strategies_no_delete BEFORE DELETE ON strategies BEGIN SELECT RAISE(ABORT, 'immutable version'); END;
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, error TEXT, result TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_job ON jobs(status) WHERE status='RUNNING';
                CREATE TRIGGER IF NOT EXISTS completed_no_update BEFORE UPDATE ON jobs WHEN OLD.status='COMPLETE' BEGIN SELECT RAISE(ABORT, 'immutable result'); END;
                CREATE TRIGGER IF NOT EXISTS completed_no_delete BEFORE DELETE ON jobs WHEN OLD.status='COMPLETE' BEGIN SELECT RAISE(ABORT, 'immutable result'); END;
                PRAGMA user_version=1;
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=2)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=2000")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def save_strategy(self, raw):
        definition = validate_definition(raw)
        strategy = build_strategy(definition)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT version_id FROM strategies WHERE content_hash=?",(strategy.content_hash,)).fetchone():
                return strategy.version_id
            if c.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] >= 100:
                raise ResourceLimit("100-version local research bound reached")
            c.execute("INSERT OR IGNORE INTO strategies VALUES(?,?,?)", (strategy.version_id,strategy.content_hash,canonical(definition)))
        return strategy.version_id

    def get_strategy(self, version_id):
        identifier(version_id)
        with self.connect() as c:
            row = c.execute("SELECT * FROM strategies WHERE version_id=?",(version_id,)).fetchone()
        if row is None:
            raise ValidationError("unknown saved strategy version")
        d = json.loads(row["definition"])
        s = build_strategy(d)
        if s.version_id != row["version_id"] or s.content_hash != row["content_hash"]:
            raise ValidationError("saved strategy integrity failure")
        return d

    def list_strategies(self):
        with self.connect() as c:
            return [{"version_id":r["version_id"],"content_hash":r["content_hash"],"definition":json.loads(r["definition"])}
                    for r in c.execute("SELECT * FROM strategies ORDER BY version_id")]

    def begin_job(self,with_progress=False):
        job = "run_" + uuid.uuid4().hex
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if self.path.stat().st_size > 128 * 1024 * 1024:
                raise ResourceLimit("128 MiB research DB bound reached")
            try:
                c.execute("INSERT INTO jobs(id,status) VALUES(?,'RUNNING')",(job,))
                if with_progress:
                    c.execute("INSERT INTO job_progress VALUES(?,0,'ADMITTED',?)",(job,datetime.now(timezone.utc).isoformat(timespec="milliseconds")))
            except sqlite3.IntegrityError:
                raise ResourceLimit("another local research job is running (or requires explicit interrupted-job recovery)") from None
        return job

    def finish_job(self, job, result=None, error=None):
        body = canonical(result) if result is not None else None
        if body is not None and len(body.encode()) > MAX_RESULT_BYTES:
            raise ResourceLimit("16 MiB result bound reached; no truncated result accepted")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            stored = sum(p.stat().st_size for p in self.root.glob("backtester-research.sqlite3*") if p.is_file())
            if body is not None and stored + 2*len(body.encode()) > 128*1024*1024:
                raise ResourceLimit("research SQLite/WAL output bound reached; no partial result accepted")
            updated = c.execute("UPDATE jobs SET status=?,result=?,error=? WHERE id=? AND status='RUNNING'",
                                ("COMPLETE" if result is not None else "FAILED",body,error,job)).rowcount
            if updated != 1:
                raise ValidationError("job is not RUNNING")

    def get_job(self, job):
        identifier(job)
        with self.connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?",(job,)).fetchone()
        if row is None:
            raise ValidationError("unknown research run")
        return {"id":row["id"],"status":row["status"],"error":row["error"],"result":json.loads(row["result"]) if row["result"] else None}

    def list_jobs(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT id,status,error FROM jobs ORDER BY rowid DESC")]

    def recover_interrupted(self):
        """Owner CLI only, after all local servers/workers have stopped."""
        with self.connect() as c:
            return c.execute("UPDATE jobs SET status='INTERRUPTED',error='Owner recovery after stopped workers' WHERE status='RUNNING'").rowcount
