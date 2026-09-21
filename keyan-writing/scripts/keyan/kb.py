"""知识库检索桥接：优先调用 consulting-kb-retrieval，无网络/无凭据时回退到本地 wiki 检索。"""
import json
import os
import re
import subprocess
import sys
import time
import hashlib
from pathlib import Path

from .cache import atomic_dump_json, sha256_file, sha256_json

KB_ENV = "KEYAN_KB_ROOT"
KB_DIR_NAME = "consulting-kb-retrieval"

_QUERY_CACHE = {}
_KB_FINGERPRINTS = {}

_DOC_PAGE = re.compile(r"文档名称：\s*([^\s页]+)[^\n]{0,12}?页码：\s*(\d+(?:-\d+)?)")


def find_kb_root(skill_root=None, extra_candidates=()):
    candidates = []
    env = os.environ.get(KB_ENV)
    if env:
        candidates.append(Path(env))
    if skill_root:
        skill_root = Path(skill_root)
        candidates.extend([skill_root.parent / KB_DIR_NAME, skill_root / KB_DIR_NAME,
                           skill_root.parent.parent / KB_DIR_NAME])
    candidates.extend(Path(item) for item in extra_candidates)
    candidates.extend([Path.home() / KB_DIR_NAME, Path("D:/") / "可研1" / KB_DIR_NAME])
    for candidate in candidates:
        try:
            if candidate and Path(candidate, "scripts", "retrieve.py").exists():
                return Path(candidate).resolve()
        except OSError:
            continue
    return None


def list_libraries(kb_root):
    path = Path(kb_root) / "datasets.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    names = list((payload.get("datasets") or {}).keys())
    return names


def _wiki_files(kb_root):
    wiki = Path(kb_root) / "wiki"
    return sorted(wiki.glob("*.md")) if wiki.is_dir() else []


def offline_wiki_search(kb_root, query, top_k=5):
    """无凭据/无网络时的本地近似检索：wiki/*.md 段落级打分（字符 2-gram 重合）。"""
    query = (query or "").strip()
    if not query:
        return []
    grams = {query[i:i + 2] for i in range(max(len(query) - 1, 1))}
    hits = []
    for path in _wiki_files(kb_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        for block in blocks:
            if len(block) < 12:
                continue
            score = sum(1 for gram in grams if gram in block)
            if score:
                hits.append({"source": path.name, "score": round(score / max(len(grams), 1), 4),
                             "content": block[:600]})
    hits.sort(key=lambda item: -item["score"])
    return hits[:top_k]


def _kb_fingerprint(kb_root):
    root = Path(kb_root).resolve()
    paths = []
    for fixed in (root / "datasets.json", root / "scripts" / "retrieve.py"):
        if fixed.is_file():
            paths.append(fixed)
    wiki = root / "wiki"
    if wiki.is_dir():
        paths.extend(sorted(wiki.glob("*.md")))
    manifest = [(str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
                for path in paths]
    cached = _KB_FINGERPRINTS.get(str(root))
    if cached and cached[0] == manifest:
        return cached[1]
    fingerprint = sha256_json([{"path": str(path.relative_to(root)).replace("\\", "/"),
                                "sha256": sha256_file(path)} for path in paths])
    _KB_FINGERPRINTS[str(root)] = (manifest, fingerprint)
    return fingerprint


def _disk_cache_path(cache_dir, cache_key):
    digest = hashlib.sha256(sha256_json(cache_key).encode("ascii")).hexdigest()
    return Path(cache_dir) / "kb" / (digest + ".json")


def _load_disk_cache(path, *, ttl):
    path = Path(path)
    if not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(wrapper.get("created_at", 0)) > ttl:
        return None
    payload = wrapper.get("payload")
    return payload if isinstance(payload, dict) else None


def _save_disk_cache(path, payload):
    atomic_dump_json(path, {"created_at": time.time(), "payload": payload})


def search(kb_root, query, *, kb_names=None, top_k=4, timeout=180, allow_offline_fallback=True,
           cache_dir=None, refresh=False, cache_ttl=86400):
    """调用知识库；返回 {"status","backend","hits","diagnostics"}。"""
    if not kb_root:
        return {"status": "unavailable", "backend": "none", "hits": [],
                "diagnostics": ["kb_root_missing: 未找到 consulting-kb-retrieval 技能目录"]}
    retrieve = Path(kb_root) / "scripts" / "retrieve.py"
    names = kb_names or list_libraries(kb_root)
    fingerprint = _kb_fingerprint(kb_root)
    cache_key = (str(Path(kb_root).resolve()), query, ",".join(names), top_k, fingerprint)
    if not refresh and cache_key in _QUERY_CACHE:
        result = dict(_QUERY_CACHE[cache_key])
        result["cache"] = "memory"
        return result
    disk_path = _disk_cache_path(cache_dir, cache_key) if cache_dir else None
    if disk_path and not refresh:
        cached = _load_disk_cache(disk_path, ttl=cache_ttl)
        if cached is not None:
            _QUERY_CACHE[cache_key] = cached
            result = dict(cached)
            result["cache"] = "disk"
            return result
    if retrieve.exists() and names:
        command = [sys.executable, str(retrieve), "--kb", ",".join(names),
                   "--query", query, "--json", "--top-k", str(top_k)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                                       encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"status": "error", "backend": "dify", "hits": [],
                      "diagnostics": ["kb_call_failed: %s" % exc]}
            _QUERY_CACHE[cache_key] = result
            return result
        if completed.returncode == 0:
            hits = _parse_hits(completed.stdout)
            if hits:
                result = {"status": "ok", "backend": "dify", "hits": hits, "diagnostics": []}
                _QUERY_CACHE[cache_key] = result
                if disk_path:
                    _save_disk_cache(disk_path, result)
                result = dict(result)
                result["cache"] = "miss"
                return result
        else:
            diagnostics = ["kb_call_failed: exit=%s" % completed.returncode,
                           (completed.stderr or "").strip()[:300]]
            if not allow_offline_fallback:
                result = {"status": "error", "backend": "dify", "hits": [], "diagnostics": diagnostics}
                _QUERY_CACHE[cache_key] = result
                return result
    hits = offline_wiki_search(kb_root, query, top_k=top_k)
    result = {"status": "ok" if hits else "empty", "backend": "wiki-offline", "hits": hits,
              "diagnostics": ["kb_offline_fallback: 使用本地 wiki 检索（非 Dify 知识库）"]}
    _QUERY_CACHE[cache_key] = result
    if disk_path and hits:
        _save_disk_cache(disk_path, result)
    result = dict(result)
    result["cache"] = "miss"
    return result


def _parse_hits(stdout):
    text = (stdout or "").strip()
    if not text:
        return []
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None
    hits = []
    if isinstance(payload, dict):
        for key in ("results", "hits", "data", "records"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or item.get("text") or item.get("segment") or "")
            doc_name = str(item.get("doc") or item.get("文档名称") or item.get("document")
                           or item.get("source") or "")
            page = str(item.get("页码") or item.get("position") or item.get("page") or "")
            if not doc_name or not page:
                found = _DOC_PAGE.search(content)
                if found:
                    doc_name = doc_name or found.group(1)
                    page = page or found.group(2)
            hits.append({
                "source": doc_name,
                "kb": str(item.get("kb") or ""),
                "page": page,
                "score": item.get("score"),
                "content": content[:600],
            })
    return hits
