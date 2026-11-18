"""Contract tests for optional local cross-encoder reranking, using a fake engine."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reranker


class FakeEngine:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def rerank(self, query, documents, batch_size=8):
        documents = list(documents)
        self.calls.append((query, documents, batch_size))
        return iter(self.scores)


def row(pdf_page, start_word, text):
    return {"pdf_page": pdf_page, "start_word": start_word, "text": text}


def test_rank_passages_orders_by_descending_score(monkeypatch):
    rows = [row(10, 0, "low"), row(5, 0, "high"), row(7, 0, "mid")]
    engine = FakeEngine([0.1, 0.9, 0.5])
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: engine)
    ranked = reranker.rank_passages("query", rows)
    assert [r["pdf_page"] for r in ranked] == [5, 7, 10]
    assert engine.calls[0][0] == "query"
    assert engine.calls[0][1] == ["low", "high", "mid"]


def test_rank_passages_breaks_ties_by_location(monkeypatch):
    rows = [row(10, 50, "a"), row(10, 0, "b"), row(5, 0, "c")]
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: FakeEngine([0.5, 0.5, 0.9]))
    ranked = reranker.rank_passages("query", rows)
    assert [(r["pdf_page"], r["start_word"]) for r in ranked] == [(5, 0), (10, 0), (10, 50)]


def test_empty_rows_short_circuit(monkeypatch):
    engine = FakeEngine([])
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: engine)
    assert reranker.rank_passages("query", []) == []
    assert engine.calls == []


def test_mismatched_score_count_raises(monkeypatch):
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: FakeEngine([0.1]))
    with pytest.raises(ValueError, match="score count"):
        reranker.rank_passages("query", [row(1, 0, "a"), row(2, 0, "b")])


def test_non_finite_score_raises(monkeypatch):
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: FakeEngine([float("nan")]))
    with pytest.raises(ValueError, match="non-finite"):
        reranker.rank_passages("query", [row(1, 0, "a")])


def test_missing_dependency_is_explicit_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("Reranking requires optional dependency fastembed==0.9.1")
    monkeypatch.setattr(reranker, "_engine", boom)
    with pytest.raises(RuntimeError, match="optional dependency"):
        reranker.rank_passages("query", [row(1, 0, "a")])


def test_engine_failure_is_wrapped(monkeypatch):
    class BrokenEngine:
        def rerank(self, query, documents, batch_size=8):
            raise OSError("onnxruntime crashed")
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: BrokenEngine())
    with pytest.raises(RuntimeError, match="cross-encoder reranking failed"):
        reranker.rank_passages("query", [row(1, 0, "a")])


def test_prepare_reranker_requires_existing_index(tmp_path, monkeypatch):
    monkeypatch.setattr(reranker, "_engine", lambda **kwargs: FakeEngine([]))
    with pytest.raises(FileNotFoundError, match="run index"):
        reranker.prepare_reranker(tmp_path / "missing.sqlite")


def test_prepare_reranker_sets_metadata_only_after_engine_loads(tmp_path, monkeypatch):
    db = tmp_path / "rules.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES('source_sha256','src')")
    calls = []

    def fake_engine(local_files_only=True):
        calls.append(local_files_only)
        return FakeEngine([])

    monkeypatch.setattr(reranker, "_engine", fake_engine)
    result = reranker.prepare_reranker(db)
    assert result == {"model": reranker.MODEL}
    assert calls == [False]
    with sqlite3.connect(db) as conn:
        value = conn.execute("SELECT value FROM metadata WHERE key='reranker_model'").fetchone()
    assert value == (reranker.MODEL,)


def test_prepare_reranker_does_not_write_metadata_on_load_failure(tmp_path, monkeypatch):
    db = tmp_path / "rules.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES('source_sha256','src')")

    def boom(local_files_only=True):
        raise RuntimeError("Cannot load local reranker model")

    monkeypatch.setattr(reranker, "_engine", boom)
    with pytest.raises(RuntimeError, match="Cannot load"):
        reranker.prepare_reranker(db)
    with sqlite3.connect(db) as conn:
        value = conn.execute("SELECT value FROM metadata WHERE key='reranker_model'").fetchone()
    assert value is None
