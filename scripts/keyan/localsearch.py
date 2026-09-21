"""本地原文检索：精确匹配 + 字符 bigram 打分；可选 SQLite 持久化索引。"""
import hashlib
import math
import re
import sqlite3
from pathlib import Path

from .cache import sha256_file

_PUNCT = re.compile(r"[\s，。；：、（）()〔〕【】《》<>“”‘’\"'·,.;:!?\-—/\\|]+")
_INDEX_SCHEMA = "2"


def _grams(text):
    text = _PUNCT.sub("", text or "")
    return {text[i:i + 2] for i in range(max(len(text) - 1, 1))} if text else set()


def search_text(text, query, *, top_k=5, window=6, min_len=12):
    """在单份文本里检索：返回 [{line, text, score, match}]。"""
    lines = text.splitlines()
    hits = []
    query_norm = _PUNCT.sub("", query)
    if not query_norm:
        return []
    if query_norm in _PUNCT.sub("", text):
        for index, line in enumerate(lines, start=1):
            if query_norm.lower() in _PUNCT.sub("", line).lower():
                hits.append({"line": index, "text": line.strip(), "score": 1.0, "match": "exact"})
    if not hits:
        query_grams = _grams(query)
        scored = []
        for start in range(0, max(len(lines) - window + 1, 1), max(window // 2, 1)):
            block = "\n".join(lines[start:start + window]).strip()
            if len(block) < min_len:
                continue
            block_grams = _grams(block)
            if not block_grams:
                continue
            overlap = len(query_grams & block_grams)
            if overlap == 0:
                continue
            score = overlap / math.sqrt(max(len(query_grams), 1) * max(len(block_grams), 1))
            scored.append({"line": start + 1, "text": block[:400], "score": round(score, 4),
                           "match": "bm25"})
        scored.sort(key=lambda item: -item["score"])
        hits = scored[:top_k]
    return hits[:top_k]


def _database_path(cache_dir, directory):
    key = hashlib.sha256(str(Path(directory).resolve()).encode("utf-8")).hexdigest()[:20]
    root = Path(cache_dir) / "search"
    root.mkdir(parents=True, exist_ok=True)
    return root / ("%s.sqlite" % key)


def _connect(path):
    connection = sqlite3.connect(str(path), timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = connection.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    reset = bool(row and row[0] != _INDEX_SCHEMA)
    if reset:
        connection.executescript("""
            DROP TABLE IF EXISTS grams;
            DROP TABLE IF EXISTS blocks;
            DROP TABLE IF EXISTS lines;
            DROP TABLE IF EXISTS files;
            DROP TABLE IF EXISTS meta;
        """)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            norm_text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lines(
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            line_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            norm TEXT NOT NULL,
            PRIMARY KEY(file_id, line_no)
        );
        CREATE TABLE IF NOT EXISTS blocks(
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            line_no INTEGER NOT NULL,
            text TEXT NOT NULL,
            grams TEXT NOT NULL,
            gram_count INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_file ON blocks(file_id);
    """)
    connection.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema',?)", (_INDEX_SCHEMA,))
    connection.commit()
    if reset:
        connection.execute("VACUUM")
    return connection


def _index_file(connection, path, *, window=6, min_len=12):
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    digest = sha256_file(path)
    norm_text = _PUNCT.sub("", text)
    cursor = connection.execute(
        "INSERT INTO files(path,name,size,mtime_ns,sha256,norm_text) VALUES(?,?,?,?,?,?)",
        (str(path.resolve()), path.name, stat.st_size, stat.st_mtime_ns, digest, norm_text))
    file_id = cursor.lastrowid
    lines = text.splitlines()
    connection.executemany(
        "INSERT INTO lines(file_id,line_no,text,norm) VALUES(?,?,?,?)",
        ((file_id, number, line.strip(), _PUNCT.sub("", line).lower())
         for number, line in enumerate(lines, start=1)))
    step = max(window // 2, 1)
    for start in range(0, max(len(lines) - window + 1, 1), step):
        block = "\n".join(lines[start:start + window]).strip()
        if len(block) < min_len:
            continue
        grams = sorted(_grams(block))
        if not grams:
            continue
        connection.execute(
            "INSERT INTO blocks(file_id,line_no,text,grams,gram_count) VALUES(?,?,?,?,?)",
            (file_id, start + 1, block[:400], "\x1f".join(grams), len(grams)))


def _sync_index(connection, directory, pattern="*.md", *, refresh=False):
    directory = Path(directory).resolve()
    paths = [path for path in sorted(directory.rglob(pattern)) if path.is_file()]
    current = {str(path.resolve()): path for path in paths}
    existing = {row[0]: {"id": row[1], "size": row[2], "mtime_ns": row[3], "sha256": row[4]}
                for row in connection.execute("SELECT path,id,size,mtime_ns,sha256 FROM files")}
    for missing in set(existing) - set(current):
        connection.execute("DELETE FROM files WHERE id=?", (existing[missing]["id"],))
    for key, path in current.items():
        stat = path.stat()
        old = existing.get(key)
        unchanged = (old and not refresh and old["size"] == stat.st_size
                     and old["mtime_ns"] == stat.st_mtime_ns)
        if unchanged:
            continue
        digest = sha256_file(path)
        if old and not refresh and old["sha256"] == digest:
            connection.execute("UPDATE files SET size=?,mtime_ns=? WHERE id=?",
                               (stat.st_size, stat.st_mtime_ns, old["id"]))
            continue
        if old:
            connection.execute("DELETE FROM files WHERE id=?", (old["id"],))
        _index_file(connection, path)
    connection.commit()


def _indexed_file_hits(connection, file_id, query, *, top_k=5):
    query_norm = _PUNCT.sub("", query)
    if not query_norm:
        return []
    row = connection.execute("SELECT norm_text FROM files WHERE id=?", (file_id,)).fetchone()
    if row and query_norm in row[0]:
        exact = []
        needle = query_norm.lower()
        for line_no, text, norm in connection.execute(
                "SELECT line_no,text,norm FROM lines WHERE file_id=? ORDER BY line_no", (file_id,)):
            if needle in norm:
                exact.append({"line": line_no, "text": text, "score": 1.0, "match": "exact"})
        if exact:
            return exact[:top_k]
    query_grams = sorted(_grams(query))
    if not query_grams:
        return []
    query_set = set(query_grams)
    rows = connection.execute(
        "SELECT line_no,text,grams,gram_count FROM blocks WHERE file_id=? ORDER BY line_no",
        (file_id,)).fetchall()
    scored = []
    for line_no, text, encoded_grams, gram_count in rows:
        overlap = len(query_set.intersection(encoded_grams.split("\x1f")))
        if overlap == 0:
            continue
        score = overlap / math.sqrt(max(len(query_grams), 1) * max(gram_count, 1))
        scored.append({"line": line_no, "text": text, "score": round(score, 4), "match": "bm25"})
    scored.sort(key=lambda item: -item["score"])
    return scored[:top_k]


def _indexed_search(directory, query, *, top_k, pattern, exact_only, exclude_names,
                    cache_dir, refresh):
    connection = _connect(_database_path(cache_dir, directory))
    try:
        _sync_index(connection, directory, pattern, refresh=refresh)
        excluded = set(exclude_names)
        results = []
        for file_id, name, path in connection.execute("SELECT id,name,path FROM files ORDER BY path"):
            if name in excluded:
                continue
            for hit in _indexed_file_hits(connection, file_id, query, top_k=top_k):
                if exact_only and hit["match"] != "exact":
                    continue
                results.append({"file": name, "path": path, **hit})
        results.sort(key=lambda item: (-item["score"], item["file"], item["line"]))
        return results[:top_k]
    finally:
        connection.close()


def search_dir(directory, query, *, top_k=5, pattern="*.md", exact_only=False,
               exclude_names=(), cache_dir=None, refresh=False):
    directory = Path(directory)
    if not directory.exists():
        return []
    if cache_dir:
        try:
            return _indexed_search(directory, query, top_k=top_k, pattern=pattern,
                                   exact_only=exact_only, exclude_names=exclude_names,
                                   cache_dir=cache_dir, refresh=refresh)
        except sqlite3.Error:
            pass
    results = []
    excluded = set(exclude_names)
    for path in sorted(directory.rglob(pattern)):
        if path.name in excluded:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for hit in search_text(text, query, top_k=top_k):
            if exact_only and hit["match"] != "exact":
                continue
            results.append({"file": path.name, "path": str(path), **hit})
    results.sort(key=lambda item: (-item["score"], item["file"], item["line"]))
    return results[:top_k]
