from .cache import now
from datetime import datetime,timezone,timedelta


class Progress:
    def __init__(self,store):
        self.store=store
        with store.connect() as c:c.execute("CREATE TABLE IF NOT EXISTS job_progress(job_id TEXT PRIMARY KEY,percent INTEGER NOT NULL,stage TEXT NOT NULL,updated_at TEXT NOT NULL)")
    def set(self,job,percent,stage):
        with self.store.connect() as c:
            c.execute("INSERT INTO job_progress VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET percent=excluded.percent,stage=excluded.stage,updated_at=excluded.updated_at",(job,percent,stage,now()))
    def get(self,job):
        with self.store.connect() as c:row=c.execute("SELECT percent,stage,updated_at FROM job_progress WHERE job_id=?",(job,)).fetchone()
        return dict(row) if row else {"percent":0,"stage":"ADMITTED","updated_at":None}

    def recover_stale(self):
        # Bounded preparation+worker is under80s. A three-minute stale phase
        # never becomes a successful report, even if an old process resumes.
        cutoff=(datetime.now(timezone.utc)-timedelta(seconds=180)).isoformat(timespec="milliseconds")
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            jobs=c.execute("SELECT j.id FROM jobs j JOIN job_progress p ON p.job_id=j.id WHERE j.status='RUNNING' AND p.updated_at<?",(cutoff,)).fetchall()
            for row in jobs:
                c.execute("UPDATE jobs SET status='INTERRUPTED',error='Worker interrupted or phase timed out; no completed result accepted' WHERE id=? AND status='RUNNING'",(row[0],))
                c.execute("UPDATE job_progress SET percent=100,stage='INTERRUPTED',updated_at=? WHERE job_id=?",(now(),row[0]))
        return len(jobs)
