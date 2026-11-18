from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import json, hashlib, re

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def read_json(path: Path, default=None):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path: Path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def sha256_file(path: Path, chunk=1024*1024):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def slug(value: str):
    s = re.sub(r"[^A-Za-z0-9А-Яа-я_-]+", "-", value.strip()).strip("-")
    return s or "dd-project"
