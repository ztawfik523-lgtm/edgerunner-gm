"""Synthetic tests for conservative table extraction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout


class FakeTable:
    def __init__(self, rows, bbox=(1, 2, 3, 4)):
        self._rows = rows
        self.bbox = bbox

    def extract(self):
        return self._rows


class FakePage:
    def __init__(self, tables):
        self.tables = tables
        self.strategy = None

    def find_tables(self, *, strategy):
        self.strategy = strategy
        return type("Found", (), {"tables": self.tables})()


def test_extracts_normalized_source_cells_and_preserves_empty_cells():
    table = FakeTable([[" A\n B ", None], ["C", " D  E"], ["F", "G"]])
    page = FakePage([table])
    assert layout.extract_tables(page) == [
        {"bbox": (1, 2, 3, 4), "rows": [["A B", ""], ["C", "D E"], ["F", "G"]]}
    ]
    assert page.strategy == "lines"


def test_rejects_oversized_cell():
    page = FakePage([FakeTable([["x" * 601, "value"], ["a", "b"]])])
    assert layout.extract_tables(page) == []


def test_rejects_tables_without_two_populated_rows():
    page = FakePage([FakeTable([["a", "b"], ["only one", None], [None, ""]])])
    assert layout.extract_tables(page) == []


def test_requires_at_least_two_rows_and_columns():
    page = FakePage([FakeTable([["a", "b"]]), FakeTable([["a"], ["b"]])])
    assert layout.extract_tables(page) == []


def test_serialization_numbers_tables_and_keeps_empty_cells():
    tables = [
        {"bbox": (0, 0, 1, 1), "rows": [["Name", "Value"], ["item", ""]]},
        {"bbox": (1, 1, 2, 2), "rows": [["left", "right"]]},
    ]
    assert layout.table_text(tables) == (
        "Table 1:\nName | Value\nitem | \n\nTable 2:\nleft | right"
    )


def test_empty_serialization_is_empty():
    assert layout.table_text([]) == ""
