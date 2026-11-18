#!/usr/bin/env python3
"""Measure ranked page retrieval; output contains no private rulebook text."""
import argparse
import json
import re
import time
from pathlib import Path

from redkb import DEFAULT_DB, inspect_index, search_pages


def benchmark(db: Path, files: list[Path], lexical_only: bool = False) -> dict:
    outcomes = []
    for file in files:
        for case in json.loads(file.read_text()):
            start = time.perf_counter()
            results = (search_pages(db, case['query'], 5, lexical_only=True) if lexical_only
                       else search_pages(db, case['query'], 5))
            pages = [r['printed_page'] for r in results]
            rank = next((i for i, page in enumerate(pages, 1) if page in case['expected_printed_pages']), None)
            outcome = {'set': file.name, 'query': case['query'], 'expected': case['expected_printed_pages'],
                       'actual': pages, 'rank': rank, 'milliseconds': round((time.perf_counter() - start) * 1000, 2)}
            if case.get('evidence_patterns'):
                outcome['excerpt_evidence_found'] = any(
                    all(re.search(pattern, re.sub(r'\s+', ' ', row.get('text', row.get('excerpt', ''))), re.I)
                        for pattern in case['evidence_patterns'])
                    for row in results if row['printed_page'] in case['expected_printed_pages'])
            outcomes.append(outcome)
    count = len(outcomes)
    evidence_cases = [r for r in outcomes if 'excerpt_evidence_found' in r]
    return {'source_sha256': inspect_index(db)['source_sha256'], 'mode': 'lexical_only' if lexical_only else 'auto', 'total': count,
            'hit_at_1': sum(r['rank'] == 1 for r in outcomes) / count if count else 0,
            'hit_at_5': sum(r['rank'] is not None for r in outcomes) / count if count else 0,
            'mrr_at_5': sum(1 / r['rank'] for r in outcomes if r['rank']) / count if count else 0,
            'evidence_cases': len(evidence_cases),
            'excerpt_evidence_hit_at_5': sum(r['excerpt_evidence_found'] for r in evidence_cases) / len(evidence_cases) if evidence_cases else None,
            'cases': outcomes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--lexical-only', action='store_true')
    parser.add_argument('cases', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.db, args.cases, args.lexical_only), indent=2))
