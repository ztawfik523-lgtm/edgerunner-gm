"""Optional CPU-local cross-encoder reranking of retrieved passages."""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any

from index_lock import index_lock

MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
_CACHE = Path.home() / ".cache/cyberpunk-red-gm/models"


@lru_cache(maxsize=2)
def _engine(local_files_only: bool = True) -> Any:
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RuntimeError("Reranking requires optional dependency fastembed==0.9.1") from exc
    _CACHE.mkdir(parents=True, exist_ok=True)
    try:
        return TextCrossEncoder(model_name=MODEL, cache_dir=str(_CACHE), threads=2,
                                providers=["CPUExecutionProvider"], local_files_only=local_files_only)
    except Exception as exc:
        raise RuntimeError(f"Cannot load local reranker model {MODEL}; prepare it before offline use") from exc


def prepare_reranker(db_path: Path) -> dict[str, str]:
    """Download/cache the public model, then activate it in an existing index."""
    db_path = Path(db_path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError("Index missing; run index before preparing reranker")
    # Do not change the active index unless model acquisition/initialization worked.
    _engine(local_files_only=False)
    with index_lock(db_path), closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO metadata(key,value) VALUES('reranker_model',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (MODEL,))
    return {"model": MODEL}


def rank_passages(query: str, rows: list[Any]) -> list[Any]:
    """Rank candidate rows by finite cross-encoder score, stably breaking ties by location."""
    if not rows:
        return []
    try:
        scores = list(_engine(local_files_only=True).rerank(
            query, [row["text"] for row in rows], batch_size=8))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("Local cross-encoder reranking failed") from exc
    if len(scores) != len(rows):
        raise ValueError("Reranker returned an unexpected score count")
    normalized = []
    for row, score in zip(rows, scores):
        value = float(score)
        if not math.isfinite(value):
            raise ValueError("Reranker returned a non-finite score")
        normalized.append((row, value))
    normalized.sort(key=lambda item: (-item[1], int(item[0]["pdf_page"]), int(item[0]["start_word"])))
    return [row for row, _ in normalized]
