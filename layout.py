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


def _is_bold(span: dict[str, Any]) -> bool:
    font = str(span.get("font", "")).casefold()
    return bool(int(span.get("flags", 0)) & 16) or "bold" in font or "black" in font


def run_in_name(spans: list[dict[str, Any]]) -> str:
    """The bold "Name:" that opens a run-in paragraph, read from the first line's spans."""
    lead, i = "", 0
    while i < len(spans) and ":" not in lead and (_is_bold(spans[i]) or not spans[i].get("text", "").strip()):
        lead += spans[i].get("text", "")
        i += 1
    rest = "".join(span.get("text", "") for span in spans[i:])
    if ":" not in lead and not rest.lstrip().startswith(":"):
        return ""
    name = flat(clean_text(lead.split(":", 1)[0]))
    return name if 0 < len(name) <= 60 else ""


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
            if _is_bold(span):
                bold_chars += weight
    text = _collapse_lines(clean_text("\n".join(lines)))
    if not text:
        return None
    x0, y0, x1, y1 = (float(v) for v in block["bbox"])
    first = next((line.get("spans", []) for line in block.get("lines", [])
                  if any(span.get("text", "").strip() for span in line.get("spans", []))), [])
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text,
            "size": round(max(sizes), 1) if sizes else 0.0,
            "bold": bool(chars) and bold_chars * 2 > chars, "runin": run_in_name(first)}


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
    result = {"pdf_page": pdf_page, "width": float(page.rect.width), "height": float(page.rect.height),
              "blocks": blocks, "tables": tables}
    if all(any(label in block["text"] for block in blocks) for label in ("Hit Points", "Skill Bases")):
        result["stat_blocks"], result["stat_notes"] = parse_stat_blocks(visible_lines(page))
    return result


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



# --------------------------------------------------------------------------
# NPC stat blocks: a fixed grid of labelled values beside a vertical name
# --------------------------------------------------------------------------

STAT_LABELS = ("INT", "REF", "DEX", "TECH", "COOL", "WILL", "LUCK", "MOVE", "BODY", "EMP")
_STAT_VALUE = re.compile(r"(\d{1,2})(?:\s*\((\d{1,2})\))?|—")
_DAMAGE = re.compile(r"\d{1,2}d6")
_SKILL_BASE = re.compile(r"(.*?[^\d\s(])\s*(\d{1,2})(?:\s*\(\d{1,2}\))?")
_SECTION_LABELS = {"skills": "Skill Bases", "equipment": "Cyberware & Special Equipment", "programs": "Cyberdeck Programs"}
_TIER_NOTES = (("mini boss", r"considered Mini Boss"), ("lieutenant", r"considered Lieutenant"),
               ("mook", r"considered Mook"), ("boss", r"full on boss"))


def visible_lines(page: Any) -> list[dict[str, Any]]:
    """Text lines as drawn: characters later painted over by an opaque fill are dropped.

    Stat-block art reuses a template and covers its leftover text with filled
    shapes. Lines are also split where a wide gap separates two table cells.
    """
    fills = [(d["seqno"], d["rect"]) for d in page.get_drawings()
             if d.get("fill") is not None and (d.get("fill_opacity") or 1) >= 0.99]
    # (origin, font) -> drawn visibly; hidden and visible template text can share an origin.
    drawn: dict[tuple[float, float, str], bool] = {}
    for span in page.get_texttrace():
        for _, _, origin, box in span["chars"]:
            x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            shown = not any(seq > span["seqno"] and r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1 for seq, r in fills)
            key = (round(origin[0], 1), round(origin[1], 1), span["font"])
            drawn[key] = shown or drawn.get(key, False)
    lines = []
    for block in page.get_text("rawdict", sort=False).get("blocks", []):
        for line in block.get("lines", []):
            rotated = abs(line["dir"][1]) > 0.5
            runs: list[list[tuple[dict[str, Any], dict[str, Any]]]] = []
            for span in line["spans"]:
                shown = False
                for char in span["chars"]:
                    # The later letters of a ligature have no glyph of their own; they follow the first.
                    shown = drawn.get((round(char["origin"][0], 1), round(char["origin"][1], 1), span["font"]), shown)
                    if not shown:
                        continue
                    if not runs or not rotated and char["bbox"][0] - runs[-1][-1][0]["bbox"][2] > span["size"] * 1.2:
                        runs.append([])
                    runs[-1].append((char, span))
            for run in runs:
                text = flat(clean_text("".join(char["c"] for char, _ in run)))
                if not text:
                    continue
                inked = [(char, span) for char, span in run if char["c"].strip()]
                span = inked[0][1]
                lines.append({
                    "x0": min(c["bbox"][0] for c, _ in inked), "y0": min(c["bbox"][1] for c, _ in inked),
                    "x1": max(c["bbox"][2] for c, _ in inked), "y1": max(c["bbox"][3] for c, _ in inked),
                    "text": text, "rotated": rotated,
                    "emphasis": _is_bold(span) and bool(int(span.get("flags", 0)) & 2),
                })
    return lines


def _reading_order(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for line in sorted(lines, key=lambda ln: ln["y0"]):
        if rows and line["y0"] - rows[-1][0]["y0"] <= 5:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [line for row in rows for line in sorted(row, key=lambda ln: ln["x0"])]


def _same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["y0"] < b["y1"] - 2 and b["y0"] < a["y1"] - 2


def _label(lines: list[dict[str, Any]], pattern: str) -> dict[str, Any] | None:
    return next((ln for ln in lines if ln["text"].startswith("▶") and re.match(pattern, norm_key(ln["text"]))), None)


def _value(lines: list[dict[str, Any]], label: dict[str, Any] | None, pattern: re.Pattern[str]) -> re.Match[str] | None:
    """The matching value in a label's cell: same row, right of it, before the next label."""
    if label is None:
        return None
    limit = min((ln["x0"] for ln in lines if ln["text"].startswith("▶") and _same_row(ln, label) and ln["x0"] > label["x0"]),
                default=label["x0"] + 110)
    for line in sorted(lines, key=lambda ln: ln["x0"]):
        match = pattern.fullmatch(line["text"])
        if match and label["x0"] < line["x0"] < limit and _same_row(line, label):
            return match
    return None


def _section_texts(lines: list[dict[str, Any]]) -> dict[str, str]:
    """The labelled free-text boxes (skill bases, equipment, programs), unwrapped."""
    labels = {key: _label(lines, norm_key(title)) for key, title in _SECTION_LABELS.items()}
    out = {}
    for key, label in labels.items():
        if label is None:
            continue
        stop = min((other["y0"] - 3 for other in labels.values() if other and other["y0"] > label["y0"] + 3),
                   default=float("inf"))
        parts, bottom = [], label["y0"]
        for line in _reading_order([ln for ln in lines if ln["x0"] >= label["x0"] - 2 and label["y0"] - 4 <= ln["y0"] < stop]):
            if line["y0"] - bottom > 18:
                break
            bottom = line["y0"]
            parts.append(line["text"])
        pattern = r"▶\s*" + r"\s*".join(map(re.escape, _SECTION_LABELS[key].split())) + r"\s*"
        out[key] = flat(re.sub(pattern, "", cell_text("\n".join(parts)), flags=re.I))
    return out


def _split_list(text: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    return [part.strip() for part in re.split(r",(?![^()]*\))", text) if part.strip()]


def _weapons(lines: list[dict[str, Any]], top: float, bottom: float, left_edge: float, right: float) -> list[dict[str, str]]:
    area = [ln for ln in lines if top <= ln["y0"] < bottom - 4 and left_edge <= ln["x0"] < right and not ln["text"].startswith("▶")]
    damages = [ln for ln in area if _DAMAGE.fullmatch(ln["text"])]
    mid = lambda ln: (ln["y0"] + ln["y1"]) / 2  # noqa: E731
    weapons = []
    for damage in _reading_order(damages):
        left = max((d["x1"] for d in damages if d["x1"] < damage["x0"] and abs(mid(d) - mid(damage)) < 20), default=0)
        # A two-line name sits centred on its single damage cell.
        name = [ln for ln in area if ln not in damages and left <= ln["x0"] and ln["x1"] <= damage["x0"] + 2
                and abs(mid(ln) - mid(damage)) < 12]
        if name:
            weapons.append({"name": flat(" ".join(ln["text"] for ln in _reading_order(name))), "damage": damage["text"]})
    return weapons


def _stat_block(region: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """One block's fields, or None when its STATs or Hit Points cannot all be read."""
    stats: dict[str, int] = {}
    effective: dict[str, int] = {}
    for stat in STAT_LABELS:
        match = _value(region, _label(region, stat.lower() + "$"), _STAT_VALUE)
        if match is None:
            return None
        stats[stat] = int(match.group(1) or 0)
        if match.group(2):
            effective[stat] = int(match.group(2))
    number = re.compile(r"(\d{1,3})")
    derived = {key: _value(region, _label(region, pattern), number)
               for key, pattern in (("hit_points", "hitpoints"), ("seriously_wounded", r"ser\w*wounded"),
                                    ("death_save", "deathsave"))}
    if not name or derived["hit_points"] is None:
        return None
    block: dict[str, Any] = {"name": name, "stats": stats, "effective_stats": effective,
                             **{key: int(match.group(1)) for key, match in derived.items() if match}}
    texts = _section_texts(region)
    armor = next((ln for ln in region if re.match(r"Armor\s*:", ln["text"])), None)
    if armor is not None:
        block["armor"] = armor["text"].split(":", 1)[1].strip()
        for location in ("Head", "Body"):
            row = next((ln for ln in region if ln["text"].startswith(location) and ln["y0"] > armor["y0"]), None)
            points = row and next((m for ln in [row, *region] if _same_row(ln, row) and ln["x0"] >= row["x0"]
                                   for m in [re.search(r"(\d{1,2})\s*SP\b", ln["text"])] if m), None)
            if points:
                block[f"sp_{location.lower()}"] = int(points.group(1))
    header = next((ln for ln in region if ln["text"] == "Weapons"), None)
    skills = _label(region, "skillbases")
    if header is not None and skills is not None:
        block["weapons"] = _weapons(region, header["y1"] - 3, skills["y0"], skills["x0"] - 2,
                                    armor["x0"] - 5 if armor else float("inf"))
    block["skill_bases"], block["unparsed_skills"] = [], []
    for part in _split_list(texts.get("skills", "")):
        match = _SKILL_BASE.fullmatch(part)
        if match:
            block["skill_bases"].append({"name": match.group(1), "base": int(match.group(2))})
        else:
            block["unparsed_skills"].append(part)
    block.update({key: texts[key] for key in ("equipment", "programs") if texts.get(key)})
    return block


def parse_stat_blocks(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(stat blocks, emphasised notes) from one page's visible lines.

    Each block starts at its INT label and runs to the next one; the NPC's name
    is the vertical text to the left.
    """
    upright = [ln for ln in lines if not ln["rotated"] and not ln.get("emphasis")]
    anchors = sorted((ln for ln in upright if ln["text"].startswith("▶") and norm_key(ln["text"]) == "int"),
                     key=lambda ln: ln["y0"])
    blocks = []
    for anchor, following in zip(anchors, [*anchors[1:], None]):
        top, bottom = anchor["y0"] - 8, following["y0"] - 8 if following else float("inf")
        names = [ln for ln in lines if ln["rotated"] and ln["x1"] <= anchor["x0"] and top <= (ln["y0"] + ln["y1"]) / 2 < bottom]
        name = flat(" ".join(ln["text"] for ln in sorted(names, key=lambda ln: ln["x0"]))).title()
        block = _stat_block([ln for ln in upright if top <= ln["y0"] < bottom], name)
        if block:
            blocks.append(block)
    notes: list[str] = []
    previous = None
    for line in _reading_order([ln for ln in lines if ln.get("emphasis") and not ln["rotated"]]):
        if previous is not None and line["y0"] - previous <= 18:
            notes[-1] = f"{notes[-1]} {line['text']}"
        else:
            notes.append(line["text"])
        previous = line["y0"]
    return blocks, notes


def assign_tiers(pages: list[dict[str, Any]]) -> None:
    """Tag stat blocks with the threat tier the book's footnotes give them, in place."""
    notes = [note for page in pages for note in page.get("stat_notes", [])]
    for block in (block for page in pages for block in page.get("stat_blocks", [])):
        for tier, pattern in _TIER_NOTES:
            if any(re.search(pattern, note, re.I) and norm_key(block["name"]) in norm_key(note) for note in notes):
                block["tier"] = tier
                break
