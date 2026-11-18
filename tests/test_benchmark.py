import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark


def test_rank_metrics(tmp_path, monkeypatch):
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'query': 'one', 'expected_printed_pages': [130]},
                                 {'query': 'two', 'expected_printed_pages': [130]}]))
    monkeypatch.setattr(benchmark, 'inspect_index', lambda db: {'source_sha256': 'source'})
    monkeypatch.setattr(benchmark, 'search_pages', lambda db, query, limit: [
        {'printed_page': 130 if query == 'one' else 129}, {'printed_page': 130}])
    result = benchmark.benchmark(tmp_path / 'unused', [cases])
    assert result['hit_at_1'] == 0.5
    assert result['hit_at_5'] == 1
    assert result['mrr_at_5'] == 0.75


def test_evidence_metrics_do_not_confuse_page_hits_with_sufficient_excerpts(tmp_path, monkeypatch):
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'query': 'rule', 'expected_printed_pages': [130],
                                  'evidence_patterns': ['natural 10', 'another 1d10']}]))
    monkeypatch.setattr(benchmark, 'inspect_index', lambda db: {'source_sha256': 'source'})
    monkeypatch.setattr(benchmark, 'search_pages', lambda *args: [
        {'printed_page': 130, 'excerpt': 'The words natural 10 occur, but the procedure is absent.'}])
    result = benchmark.benchmark(tmp_path / 'unused', [cases])
    assert result['hit_at_5'] == 1
    assert result['excerpt_evidence_hit_at_5'] == 0
