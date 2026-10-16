"""Explicit hosted configuration with durable DB; secrets never serialized."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ValidationError


def storage(state_dir,*,hosted=False,database_url=None,allow_test_plaintext=False):
    url=database_url or os.environ.get("DATABASE_URL")
    if url:
        from .postgres import PostgresStore
        return PostgresStore(url,state_dir,allow_local_plaintext=allow_test_plaintext)
    if hosted:raise ValidationError("Hosted startup requires a durable PostgreSQL DATABASE_URL; runtime SQLite is not permitted")
    from .storage import Store
    return Store(state_dir)


def public_origin(value):
    if not isinstance(value,str):raise ValidationError("HKS_PUBLIC_URL must be your exact published HTTPS origin")
    p=urlsplit(value)
    if p.scheme!="https" or not p.hostname or p.username or p.password or p.path not in ("","/") or p.query or p.fragment:
        raise ValidationError("HKS_PUBLIC_URL must be an exact HTTPS origin, without path/credentials/query")
    if p.hostname in ("localhost","127.0.0.1"):raise ValidationError("Hosted origin must be the real HTTPS deployment hostname")
    return "https://"+p.netloc
