"""Single-pass page layout reading and structural text cleanup for PyMuPDF pages.

Everything here works from layout signals only (block geometry, font size,
cross-page repetition, column headers); nothing is keyed to page numbers.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

# Fraction of the page height treated as the top/bottom margin that holds
# printed page numbers and running headers.
EDGE_FRACTION = 0.085
# A margin string must recur on this many pages to count as a running header.
RUNNING_HEADER_MIN_PAGES = 4
_CREDIT = re.compile(r"^(?:art\s+|artwork\s+|illustration\s+)?by\s+[^\s].{0,60}$", re.I)
_HYPHEN_BREAK = re.compile(r"(\w+)-[ \t]*\n[ \t]*(\w+)")


def clean_text(text: str) -> str:
    """Normalize noisy PDF characters without throwing away line boundaries."""
    # NFKC would turn trademark signs into the letters "TM"; keep the sign.
    text = unicodedata.normalize("NFKC", text.replace("\u2122", "\ue000")).replace("\ue000", "\u2122")
    return text.replace("­", "").replace("​", "").replace(" ", "").replace("\x00", "")


def _collapse_lines(text: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def flat(text: str) -> str:
    """Join wrapped lines into one line of text."""
    return re.sub(r"\s+", " ", text).strip()


def norm_key(text: str) -> str:
    """Letters and digits only; robust to drop caps, line wraps and punctuation."""
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "", value)


class Hyphenation:
    """Decide whether a line-final hyphen is a word break or a real compound.

    The decision uses the book's own vocabulary: a joined form that appears
    elsewhere as one word wins; a hyphenated form that appears elsewhere inside
    a line is a real compound; otherwise a lowercase continuation is joined.
    """

    def __init__(self, words: set[str], compounds: set[str]):
        self.words = words
        self.compounds = compounds

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> "Hyphenation":
        words: set[str] = set()
        compounds: set[str] = set()
        for text in texts:
            for line in text.split("\n"):
                body = line[:-1] if line.rstrip().endswith("-") else line
                for token in re.findall(r"\w+(?:-\w+)+|\w+", body):
                    (compounds if "-" in token else words).add(token.casefold())
        return cls(words, compounds)

    def _join(self, match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        joined = left + right
        compound = f"{left}-{right}"
        if joined.casefold() in self.words:
            return joined
        if compound.casefold() in self.compounds:
            return compound
        if right[:1].islower() and not left[-1:].isdigit():
            return joined
        return compound

    def fix(self, text: str) -> str:
        return _HYPHEN_BREAK.sub(self._join, text)


def cell_text(cell: Any) -> str:
    """One-line text for a table cell (cells keep their original line breaks)."""
    if cell is None:
        return ""
    return flat(_HYPHEN_BREAK.sub(lambda m: m.group(1) + m.group(2) if m.group(2)[:1].islower() else f"{m.group(1)}-{m.group(2)}", str(cell)))


def cell_lines(cell: Any) -> list[str]:
    return [line.strip() for line in str(cell or "").split("\n") if line.strip()]


def _block_from_dict(block: dict[str, Any]) -> dict[str, Any] | None:
    lines = []
    sizes: list[float] = []
    bold_chars = 0
    chars = 0
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        text = "".join(span.get("text", "") for span in spans)
        if text.strip():
            lines.append(text)
        for span in spans:
            content = span.get("text", "")
            weight = len(content.strip())
            if not weight:
                continue
            sizes.append(float(span.get("size", 0.0)))
            chars += weight
            font = str(span.get("font", ""))
            if int(span.get("flags", 0)) & 16 or "bold" in font.casefold() or "black" in font.casefold():
                bold_chars += weight
    text = _collapse_lines(clean_text("\n".join(lines)))
    if not text:
        return None
    x0, y0, x1, y1 = (float(v) for v in block["bbox"])
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text,
            "size": round(max(sizes), 1) if sizes else 0.0,
            "bold": bool(chars) and bold_chars * 2 > chars}


def extract_tables(page: Any) -> list[dict[str, Any]]:
    """Return plausible line-detected tables, omitting likely false positives.

    Cells keep their intra-cell line breaks (spacing within a line is
    collapsed); merged cells are not inferred.
    """
    found = page.find_tables(strategy="lines")
    result: list[dict[str, Any]] = []
    for table in found.tables:
        rows = [[_collapse_lines(clean_text(str(cell))) if cell is not None else "" for cell in row] for row in table.extract()]
        # Some detected grids enclose an entire duplicated page/table as one
        # giant spanning row. Omit that row, not the useful cell rows below it.
        rows = [row for row in rows if not any(len(cell) > 600 for cell in row)]
        if len(rows) < 2:
            continue
        if max((len(row) for row in rows), default=0) < 2:
            continue
        if sum(sum(bool(cell) for cell in row) >= 2 for row in rows) < 2:
            continue
        result.append({"bbox": [float(v) for v in table.bbox], "rows": rows})
    return result


def read_page(page: Any, pdf_page: int) -> dict[str, Any]:
    """Read one PDF page once: text blocks with font evidence and tables."""
    data = page.get_text("dict", sort=False)
    blocks = []
    for raw in data.get("blocks", []):
        if raw.get("type", 0) != 0:
            continue
        block = _block_from_dict(raw)
        if block is not None:
            blocks.append(block)
    try:
        tables = extract_tables(page)
    except (AttributeError, TypeError, ValueError):
        tables = []
    return {"pdf_page": pdf_page, "width": float(page.rect.width), "height": float(page.rect.height),
            "blocks": blocks, "tables": tables}


def merge_drop_caps(pages: list[dict[str, Any]]) -> None:
    """Re-attach decorative drop-cap letters ("R" + "unning Out of Cash?"), in place."""
    for page in pages:
        blocks = page["blocks"]
        merged = []
        skip = False
        for i, block in enumerate(blocks):
            if skip:
                skip = False
                continue
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if (nxt is not None and re.fullmatch(r"[A-Z]", block["text"].strip())
                    and block["size"] >= nxt["size"] * 1.8
                    and (nxt["text"][:1].islower() or nxt["text"].split(None, 1)[0].isupper())):
                merged.append({**nxt, "text": block["text"].strip() + nxt["text"],
                               "x0": min(block["x0"], nxt["x0"]), "y0": min(block["y0"], nxt["y0"])})
                skip = True
                continue
            merged.append(block)
        page["blocks"] = merged


def apply_hyphenation(pages: list[dict[str, Any]]) -> Hyphenation:
    """Repair line-break hyphenation in blocks and table cells, in place."""
    texts = [b["text"] for p in pages for b in p["blocks"]]
    texts += [c for p in pages for t in p["tables"] for row in t["rows"] for c in row]
    hyph = Hyphenation.from_texts(texts)
    for page in pages:
        blocks = page["blocks"]
        for block in blocks:
            block["text"] = hyph.fix(block["text"])
        # A word split across two consecutive blocks ("hard-" | "driven ...").
        for first, second in zip(blocks, blocks[1:]):
            tail = re.search(r"(\w+)-$", first["text"])
            head = re.match(r"(\w+\S*)(.*)", second["text"], re.S)
            if tail and head:
                joined = hyph.fix(f"{tail.group(1)}-\n{head.group(1)}")
                compound = f"{tail.group(1)}-{re.match(r'\w+', head.group(1)).group(0)}"
                if head.group(1)[:1].isupper() and compound.casefold() not in hyph.compounds:
                    continue
                first["text"] = first["text"][:tail.start()] + joined
                second["text"] = head.group(2).lstrip() or second["text"]
        for table in page["tables"]:
            table["rows"] = [[hyph.fix(cell) for cell in row] for row in table["rows"]]
    return hyph


def _is_edge(block: dict[str, Any], height: float) -> bool:
    return block["y1"] <= height * EDGE_FRACTION or block["y0"] >= height * (1 - EDGE_FRACTION)


def _is_doubled(text: str) -> bool:
    """Blocks drawn twice (outline/shadow layers) repeat most of their word pairs."""
    words = re.findall(r"\w+", text.casefold())
    pairs = list(zip(words, words[1:]))
    if len(pairs) < 3:
        return False
    counts = Counter(pairs)
    repeated = sum(1 for pair in pairs if counts[pair] > 1)
    lines = [ln.strip() for ln in text.split("\n")]
    layered = any(len(a) >= 2 and b.startswith(a) for a, b in zip(lines, lines[1:]))
    return layered and repeated * 10 >= len(pairs) * 6


def _in_table(block: dict[str, Any], boxes: list[list[float]]) -> bool:
    return any(block["x0"] >= x0 - 2 and block["x1"] <= x1 + 2 and block["y0"] >= y0 - 2 and block["y1"] <= y1 + 2
               for x0, y0, x1, y1 in boxes)


def classify_blocks(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Tag each block's role (body, page_number, running_header, credit, doubled, heading).

    Returns document-level evidence: the body font size and running header strings.
    """
    margin_pages: dict[str, set[int]] = {}
    margin_sizes: dict[str, Counter[float]] = {}
    sizes: Counter[float] = Counter()
    edge_sizes: Counter[float] = Counter()
    for page in pages:
        for block in page["blocks"]:
            sizes[block["size"]] += len(block["text"])
            if _is_edge(block, page["height"]):
                key = flat(block["text"]).casefold()
                margin_pages.setdefault(key, set()).add(page["pdf_page"])
                margin_sizes.setdefault(key, Counter())[round(block["size"])] += 1
                edge_sizes[round(block["size"])] += 1
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0
    # Running headers share one typographic size (the modal margin size);
    # big role/chapter titles that happen to sit near the top edge do not.
    header_size = edge_sizes.most_common(1)[0][0] if edge_sizes else 0
    running = {key for key, seen in margin_pages.items()
               if len(seen) >= RUNNING_HEADER_MIN_PAGES and not re.fullmatch(r"\d{1,3}", key)
               and abs(margin_sizes[key].most_common(1)[0][0] - header_size) <= 1}
    for page in pages:
        page["printed_page"] = None
        page["running_header"] = ""
        boxes = [t["bbox"] for t in page["tables"]]
        for block in page["blocks"]:
            text = flat(block["text"])
            edge = _is_edge(block, page["height"])
            if _in_table(block, boxes):
                role = "table"
            elif edge and re.fullmatch(r"\d{1,3}", text):
                role = "page_number"
                if page["printed_page"] is None:
                    page["printed_page"] = int(text)
            elif edge and text.casefold() in running:
                role = "running_header"
                page["running_header"] = page["running_header"] or text
            elif _CREDIT.fullmatch(text) and text.split(" ", 1)[0].isupper():
                role = "credit"
            elif _is_doubled(block["text"]):
                role = "doubled"
            elif body_size and "\n" not in block["text"].strip("▶ \n") and len(text) <= 120 and (
                    block["size"] >= body_size * 1.2 or text.startswith("▶")):
                role = "heading"
            else:
                role = "body"
            block["role"] = role
    return {"body_size": body_size, "running_headers": sorted(running)}


def body_text(page: dict[str, Any]) -> str:
    """Page text without margin furniture or doubled render layers."""
    return "\n".join(b["text"] for b in page["blocks"] if b.get("role", "body") in {"body", "heading", "table"}).strip()


def table_signature(header: list[str]) -> str:
    return "|".join(norm_key(cell) for cell in header if norm_key(cell))

