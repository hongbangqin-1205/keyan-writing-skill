"""Deterministic, content-addressed caches used by the keyan pipeline."""
import hashlib
import json
import os
import tempfile
from pathlib import Path


CACHE_SCHEMA = 1


def sha256_file(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tree_fingerprint(root, pattern="*.md"):
    """Hash relative names and contents so cache invalidation is content based."""
    root = Path(root)
    rows = []
    if root.is_dir():
        for path in sorted(root.rglob(pattern)):
            if path.is_file():
                rows.append({"path": path.relative_to(root).as_posix(),
                             "sha256": sha256_file(path)})
    return sha256_json(rows)


def atomic_dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                     dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return path


def load_cache(path, fingerprint):
    path = Path(path)
    if not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if wrapper.get("schema") != CACHE_SCHEMA or wrapper.get("fingerprint") != fingerprint:
        return None
    return wrapper.get("payload")


def save_cache(path, fingerprint, payload):
    return atomic_dump_json(path, {"schema": CACHE_SCHEMA,
                                   "fingerprint": fingerprint,
                                   "payload": payload})
