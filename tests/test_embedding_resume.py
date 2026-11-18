"""Resume and privacy contracts for the local embedding cache."""
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic


class RecordingEngine:
    def __init__(self):
        self.calls = []

    def passage_embed(self, texts, **kwargs):
        self.calls.extend(texts)
        return iter([[1., 0.] if text != "beta" else [0., 1.] for text in texts])


def test_cache_reuses_hash_keyed_vectors_and_keeps_text_private(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    db = tmp_path / "rules.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);"
                           "INSERT INTO metadata VALUES('source_sha256','src');"
                           "CREATE TABLE passages(id INTEGER PRIMARY KEY,text TEXT);"
                           "INSERT INTO passages VALUES(1,'alpha'),(2,'beta');")
    engine = RecordingEngine()
    monkeypatch.setattr(semantic, "_engine", lambda **kwargs: engine)
    semantic.build_embeddings(db)
    assert engine.calls == ["alpha", "beta"]
    engine.calls.clear()
    semantic.build_embeddings(db)
    assert engine.calls == []

    cache = db.with_name(db.name + ".embedding-cache.sqlite")
    assert cache.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(cache) as conn:
        rows = conn.execute("SELECT model,text_sha256,vector FROM vectors ORDER BY text_sha256").fetchall()
    assert len(rows) == 2
    assert {row[1] for row in rows} == {hashlib.sha256(text.encode()).hexdigest() for text in ("alpha", "beta")}
    assert all(text.encode() not in cache.read_bytes() for text in ("alpha", "beta"))
