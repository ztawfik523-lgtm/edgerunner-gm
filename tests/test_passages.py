"""Passage retrieval contracts, independent of the private Corebook."""
import sqlite3
import hashlib
import sys
from pathlib import Path

import pytest
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redkb


def test_passages_have_exact_source_offsets(tmp_path):
    pdf = tmp_path / 'book.pdf'
    with pymupdf.open() as book:
        page = book.new_page()
        text = '130\nRULES\n' + '\n'.join(' '.join(['alpha', 'beta', 'gamma', 'delta'] * 4) for _ in range(28))
        page.insert_text((40, 40), text, fontsize=8)
        book.save(pdf)
    db = tmp_path / 'book.sqlite'
    redkb.build_index(pdf, db)
    with sqlite3.connect(db) as conn:
        words = conn.execute('SELECT text FROM pages').fetchone()[0].split()
        passages = conn.execute('SELECT start_word,end_word,text FROM passages ORDER BY start_word').fetchall()
    assert len(passages) > 1
    assert passages[1][0] < passages[0][1]
    for start, end, text in passages:
        assert text == ' '.join(words[start:end])
    hits = redkb.search_pages(db, 'alpha beta')
    assert len(hits) == 1  # overlapping passages do not consume multiple page slots
    assert hits[0]['source_sha256'] == redkb.inspect_index(db)['source_sha256']
    assert hits[0]['excerpt'] in [row[2] for row in passages]


def test_legacy_index_requests_rebuild(tmp_path):
    db = tmp_path / 'old.sqlite'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE metadata(key TEXT, value TEXT)')
        conn.execute("INSERT INTO metadata VALUES ('schema_version','1')")
    with pytest.raises(ValueError, match='[Rr]ebuild|index'):
        redkb.search_pages(db, 'critical success')


def test_actual_fts_index_integrity(tmp_path):
    pdf = tmp_path / 'book.pdf'
    with pymupdf.open() as book:
        page = book.new_page()
        page.insert_text((40, 40), '130\nRULES\nCritical success: natural 10. Armor reduces damage.')
        book.save(pdf)
    db = tmp_path / 'book.sqlite'
    redkb.build_index(pdf, db)
    with sqlite3.connect(db) as conn:
        # rank=1 also compares an external-content FTS index against its content.
        conn.execute("INSERT INTO passage_fts(passage_fts,rank) VALUES('integrity-check',1)")
        assert conn.execute("SELECT COUNT(*) FROM passage_fts WHERE passage_fts MATCH 'critical'").fetchone()[0] == 1
    assert redkb.search_pages(db, 'unobtainiumxyz') == []


def test_ingestion_hashes_extracted_snapshot(tmp_path, monkeypatch):
    pdf = tmp_path / 'book.pdf'
    with pymupdf.open() as book:
        book.new_page().insert_text((40, 40), '130\nRULES\nCritical success')
        book.save(pdf)
    expected = hashlib.sha256(pdf.read_bytes()).hexdigest()
    original_open = pymupdf.open

    def replace_source(*args, **kwargs):
        pdf.write_bytes(b'changed after snapshot was read')
        return original_open(*args, **kwargs)

    monkeypatch.setattr(pymupdf, 'open', replace_source)
    result = redkb.build_index(pdf, tmp_path / 'book.sqlite')
    assert result['source_sha256'] == expected


def test_mid_ingestion_failure_preserves_index(tmp_path, monkeypatch):
    pdf = tmp_path / 'book.pdf'
    with pymupdf.open() as book:
        book.new_page().insert_text((40, 40), '130\nRULES\nCritical success')
        book.save(pdf)
    db = tmp_path / 'book.sqlite'
    redkb.build_index(pdf, db)
    original = db.read_bytes()

    def fail(text):
        raise RuntimeError('interrupted extraction')

    monkeypatch.setattr(redkb, 'clean_text', fail)
    with pytest.raises(RuntimeError, match='interrupted'):
        redkb.build_index(pdf, db)
    assert db.read_bytes() == original
    assert not list(tmp_path.glob('*.building-*'))
