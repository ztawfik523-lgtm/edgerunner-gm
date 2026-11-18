"""Semantic persistence contracts with deterministic fake embeddings."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'rules.sqlite'
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);"
                           "INSERT INTO metadata VALUES('source_sha256','source');"
                           "CREATE TABLE passages(id INTEGER PRIMARY KEY,text TEXT);"
                           "INSERT INTO passages VALUES(1,'alpha'),(2,'beta');")
    return path


class Engine:
    def passage_embed(self, texts, **kwargs):
        return iter([[1., 0.], [0., 1.]])

    def query_embed(self, queries):
        return iter([[1., 0.]])


def test_semantic_round_trip_and_stale_source(db, monkeypatch):
    pytest.importorskip('numpy')
    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: Engine())
    semantic.build_embeddings(db)
    with sqlite3.connect(db) as conn:
        assert semantic.dense_candidates(conn, 'alpha')[0] == (1, 1.)
        conn.execute("UPDATE metadata SET value='changed' WHERE key='source_sha256'")
        with pytest.raises(ValueError, match='source/model'):
            semantic.dense_candidates(conn, 'alpha')


def test_no_semantic_metadata_is_optional(db):
    with sqlite3.connect(db) as conn:
        assert semantic.dense_candidates(conn, 'alpha') == []


def test_changed_snapshot_does_not_replace_embeddings(db, monkeypatch):
    pytest.importorskip('numpy')
    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: Engine())
    semantic.build_embeddings(db)
    # Add a passage with uncached text, so the resumable cache cannot skip
    # recomputation and the interruption below actually occurs mid-build.
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO passages VALUES(3,'gamma')")

    class InterruptedEngine(Engine):
        def passage_embed(self, texts, **kwargs):
            with sqlite3.connect(db) as conn:
                conn.execute("UPDATE passages SET text='changed' WHERE id=1")
            return iter([[1., 0.]])

    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: InterruptedEngine())
    with pytest.raises(RuntimeError, match='snapshot changed'):
        semantic.build_embeddings(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM passage_embeddings').fetchone()[0] == 2


def test_missing_numpy_is_operational_error(db, monkeypatch):
    pytest.importorskip('numpy')
    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: Engine())
    semantic.build_embeddings(db)
    import builtins
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == 'numpy':
            raise ModuleNotFoundError('numpy unavailable')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing)
    with sqlite3.connect(db) as conn:
        with pytest.raises(RuntimeError, match='optional dependencies'):
            semantic.dense_candidates(conn, 'alpha')


def test_dense_candidates_caches_matrix_across_clean_opens_and_invalidates(db, monkeypatch):
    pytest.importorskip('numpy')
    semantic._MATRIX_CACHE.clear()
    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: Engine())
    semantic.build_embeddings(db)

    loads = 0
    original_loader = semantic._load_validated_matrix

    def counting_loader(conn, meta):
        nonlocal loads
        loads += 1
        return original_loader(conn, meta)

    monkeypatch.setattr(semantic, '_load_validated_matrix', counting_loader)

    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        first = semantic.dense_candidates(conn, 'alpha')
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        second = semantic.dense_candidates(conn, 'alpha')
    assert first == second
    assert loads == 1

    # Rebuilding embeddings or updating DB via another connection invalidates the cache.
    class UpdatedEngine(Engine):
        def passage_embed(self, texts, **kwargs):
            return iter([[0., 1.], [1., 0.]])

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE passages SET text='alpha2' WHERE id=1")
        conn.execute("UPDATE passages SET text='beta2' WHERE id=2")
    monkeypatch.setattr(semantic, '_engine', lambda **kwargs: UpdatedEngine())
    semantic.build_embeddings(db)

    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        updated = semantic.dense_candidates(conn, 'alpha')
    assert updated[0] == (2, 1.)
    assert loads == 2
