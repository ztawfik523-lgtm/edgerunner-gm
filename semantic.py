"""Optional local dense retrieval for passage-indexed rulebooks."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections import OrderedDict
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any

from index_lock import index_lock

MODEL = "BAAI/bge-small-en-v1.5"
_CACHE = Path.home() / ".cache/cyberpunk-red-gm/models"
_MATRIX_LOCK = threading.Lock()
_MATRIX_CACHE: OrderedDict[tuple[Any, ...], tuple[tuple[int, ...], Any]] = OrderedDict()
_MATRIX_CACHE_MAX = 4


@lru_cache(maxsize=1)
def _engine(allow_download: bool = False) -> Any:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise RuntimeError("Dense retrieval requires optional dependency fastembed==0.9.1") from exc
    _CACHE.mkdir(parents=True, exist_ok=True)
    try:
        return TextEmbedding(model_name=MODEL, cache_dir=str(_CACHE), threads=2,
                             local_files_only=not allow_download, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise RuntimeError(f"Cannot load local embedding model {MODEL}; cache it before offline use") from exc


def _unit(vector: Any) -> Any:
    import numpy as np

    result = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(result))
    if not norm or not np.isfinite(norm) or not np.all(np.isfinite(result)):
        raise ValueError("Embedding model returned an invalid vector")
    return result / norm


def _blob(vector: Any) -> bytes:
    import numpy as np
    return np.asarray(vector, dtype="<f4").tobytes()


def _metadata(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key,value FROM metadata"))


def build_embeddings(db_path: Path) -> dict[str, Any]:
    """Embed a stable passage snapshot, then atomically install vectors and metadata."""
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError("Index missing; run index before embed")
    with closing(sqlite3.connect(db_path)) as conn:
        meta = _metadata(conn)
        source = meta.get("source_sha256")
        if not source:
            raise ValueError("Index is missing source_sha256 metadata")
        passages = conn.execute("SELECT id,text FROM passages ORDER BY id").fetchall()
    engine = _engine(allow_download=True)
    cache_path = db_path.with_name(db_path.name + ".embedding-cache.sqlite")
    existed = cache_path.exists()
    with closing(sqlite3.connect(cache_path, timeout=30)) as cache:
        if not existed:
            cache_path.chmod(0o600)
        cache.execute("CREATE TABLE IF NOT EXISTS vectors(model TEXT NOT NULL,text_sha256 TEXT NOT NULL,vector BLOB NOT NULL,PRIMARY KEY(model,text_sha256))")
        hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for _, text in passages]
        found = {key: blob for key, blob in cache.execute(
            "SELECT text_sha256,vector FROM vectors WHERE model=? AND text_sha256 IN (%s)" % ",".join("?" for _ in set(hashes)),
            (MODEL, *set(hashes)))} if hashes else {}
        by_hash = dict(found)
        missing = list(dict.fromkeys(key for key in hashes if key not in by_hash))
        texts_by_hash = {key: text for key, (_, text) in zip(hashes, passages)}
        dimension = None
        vectors = []
        for start in range(0, len(missing), 16):
            batch = missing[start:start + 16]
            generated = list(engine.passage_embed([texts_by_hash[key] for key in batch], batch_size=16))
            if len(generated) != len(batch):
                raise ValueError("Embedding model returned an unexpected vector count")
            completed = []
            for key, value in zip(batch, generated):
                unit = _unit(value)
                if unit.ndim != 1 or (dimension is not None and len(unit) != dimension):
                    raise ValueError("Embedding model returned inconsistent vector dimensions")
                dimension = len(unit)
                completed.append((MODEL, key, _blob(unit)))
            with cache:
                cache.executemany("INSERT INTO vectors VALUES(?,?,?) ON CONFLICT(model,text_sha256) DO UPDATE SET vector=excluded.vector", completed)
            by_hash.update((key, blob) for _, key, blob in completed)
        for blob in (by_hash[key] for key in hashes):
            import numpy as np
            vector = np.frombuffer(blob, dtype="<f4")
            if not np.all(np.isfinite(vector)) or (dimension is not None and len(vector) != dimension):
                raise ValueError("Cached embedding vectors are invalid")
            dimension = len(vector)
            vectors.append(blob)
    snapshot = [(int(pid), text) for pid, text in passages]
    with index_lock(db_path), closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            now = _metadata(conn)
            current = [(int(pid), text) for pid, text in conn.execute("SELECT id,text FROM passages ORDER BY id")]
            if now.get("source_sha256") != source or current != snapshot:
                raise RuntimeError("Index source or passage snapshot changed while embeddings were built")
            conn.execute("CREATE TABLE IF NOT EXISTS passage_embeddings(passage_id INTEGER PRIMARY KEY,vector BLOB NOT NULL)")
            conn.execute("DELETE FROM passage_embeddings")
            conn.executemany("INSERT INTO passage_embeddings VALUES(?,?)", zip((p[0] for p in passages), vectors))
            for key, value in (("semantic_model", MODEL), ("semantic_source_sha256", source), ("semantic_passage_count", str(len(passages)))):
                conn.execute("INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    resolved = str(db_path)
    with _MATRIX_LOCK:
        for cache_key in [k for k in _MATRIX_CACHE if k[0] == resolved]:
            _MATRIX_CACHE.pop(cache_key, None)
    return {"model": MODEL, "source_sha256": source, "passage_count": len(passages)}


def _cache_key(conn: sqlite3.Connection, meta: dict[str, str]) -> tuple[Any, ...] | None:
    if conn.total_changes != 0:
        return None
    db_file = ""
    for _, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main":
            db_file = filename or ""
            break
    if not db_file:
        return None
    try:
        resolved = str(Path(db_file).resolve())
        stat = os.stat(resolved)
    except OSError:
        return None
    data_version = conn.execute("PRAGMA data_version").fetchone()[0]
    return (
        resolved,
        (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size),
        int(data_version),
        meta["semantic_source_sha256"],
        meta["semantic_passage_count"],
    )


def _load_validated_matrix(conn: sqlite3.Connection, meta: dict[str, str]):
    try:
        count = int(meta["semantic_passage_count"])
        actual = int(conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0])
        rows = conn.execute("SELECT passage_id,vector FROM passage_embeddings ORDER BY passage_id").fetchall()
    except sqlite3.Error as exc:
        raise ValueError("Semantic embedding table is missing or invalid") from exc
    if count != actual or len(rows) != count:
        raise ValueError("Semantic embeddings do not match passage count")
    passage_ids = {int(row[0]) for row in conn.execute("SELECT id FROM passages")}
    if {int(row[0]) for row in rows} != passage_ids:
        raise ValueError("Semantic embeddings do not match passage IDs")
    if not rows:
        return (), None
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Dense retrieval requires requirements-semantic.txt; install optional dependencies") from exc
    matrix = np.stack([np.frombuffer(blob, dtype="<f4") for _, blob in rows])
    if matrix.ndim != 2 or not np.all(np.isfinite(matrix)):
        raise ValueError("Stored embedding vectors are invalid")
    return tuple(int(row[0]) for row in rows), matrix


def dense_candidates(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[tuple[int, float]]:
    """Return passage IDs ranked by cosine similarity (higher is better)."""
    meta = _metadata(conn)
    keys = ("semantic_model", "semantic_source_sha256", "semantic_passage_count")
    if not any(k in meta for k in keys):
        return []
    if not all(k in meta for k in keys):
        raise ValueError("Incomplete semantic metadata")
    if meta["semantic_model"] != MODEL or meta["semantic_source_sha256"] != meta.get("source_sha256"):
        raise ValueError("Semantic embeddings do not match this index source/model")
    key = _cache_key(conn, meta)
    cached = None
    if key is not None:
        with _MATRIX_LOCK:
            cached = _MATRIX_CACHE.get(key)
            if cached is not None:
                _MATRIX_CACHE.move_to_end(key)
    if cached is not None:
        passage_ids_ordered, matrix = cached
        if not passage_ids_ordered or limit <= 0:
            return []
        try:
            import numpy as np  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Dense retrieval requires requirements-semantic.txt; install optional dependencies") from exc
    else:
        passage_ids_ordered, matrix = _load_validated_matrix(conn, meta)
        if key is not None and matrix is not None:
            with _MATRIX_LOCK:
                _MATRIX_CACHE[key] = (passage_ids_ordered, matrix)
                _MATRIX_CACHE.move_to_end(key)
                while len(_MATRIX_CACHE) > _MATRIX_CACHE_MAX:
                    _MATRIX_CACHE.popitem(last=False)
        if not passage_ids_ordered or limit <= 0:
            return []
    q = _unit(next(_engine().query_embed([query])))
    if matrix.shape[1] != q.shape[0]:
        raise ValueError("Stored embedding vectors are invalid")
    scores = matrix @ q
    order = sorted(range(len(passage_ids_ordered)), key=lambda i: (-float(scores[i]), passage_ids_ordered[i]))
    return [(passage_ids_ordered[i], float(scores[i])) for i in order[:int(limit)]]
