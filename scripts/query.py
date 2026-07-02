#!/usr/bin/env python3
"""Ad-hoc retrieval + generation check (Phase 2).

Usage:
    python scripts/query.py "What is the expense ratio of HDFC Mid Cap Fund?"
    python scripts/query.py            # uses a default question
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.generator import generate_answer
from src.rag.retriever import retrieve

DEFAULT_QUERY = "What is the expense ratio of HDFC Mid Cap Fund?"


def main() -> int:
    query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY

    outcome = retrieve(query)
    print(f"Query          : {query}")
    print(f"Detected scheme: {outcome.scheme}")
    print(f"Section boost  : {outcome.section_types}")
    print(f"Top similarity : {round(outcome.top_similarity, 3)}")
    print(f"Low confidence : {outcome.low_confidence}")
    print("Retrieved chunks:")
    for r in outcome.results:
        section_type = r.metadata.get("section_type", "")
        print(f"  {r.similarity:.3f}  {section_type:20s}  {r.chunk_id}")

    answer = generate_answer(outcome)
    print()
    print(f"ANSWER      : {answer.answer}")
    print(f"SOURCE URL  : {answer.source_url}")
    print(f"LAST UPDATED: {answer.last_updated}")
    print(f"DISCLAIMER  : {answer.disclaimer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
