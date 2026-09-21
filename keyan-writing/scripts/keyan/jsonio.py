"""JSON / 路径 / 输出工具。"""
import json
import os
import re
import sys
from pathlib import Path

EXIT_CODES = {"ok": 0, "partial": 2, "conflict": 3, "error": 1}


class AppError(Exception):
    def __init__(self, message, *, status="error", diagnostics=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.diagnostics = diagnostics or []


def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        if default is None:
            raise AppError("missing json: %s" % path)
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def emit(payload):
    payload = dict(payload)
    payload.setdefault("command", "")
    payload.setdefault("status", "ok")
    payload.setdefault("artifacts", [])
    payload.setdefault("summary", {})
    payload.setdefault("diagnostics", [])
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return EXIT_CODES.get(payload["status"], 1)


_SAFE = re.compile(r"[\\/:*?\"<>|\s]+")


def slug(text, *, default="item", limit=60):
    text = (text or "").strip()
    text = _SAFE.sub("-", text)
    text = text.strip("-.")
    if not text:
        text = default
    return text[:limit]


def relative(path, base):
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)