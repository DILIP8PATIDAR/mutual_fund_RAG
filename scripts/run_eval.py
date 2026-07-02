#!/usr/bin/env python3
"""Run the Phase 5 evaluation query set and print pass/fail summary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.chat_service import process_chat
from src.index.vector_store import collection_count
from tests.eval_helpers import assert_eval_expectation, load_eval_queries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-factual",
        action="store_true",
        help="Only run safety/refusal queries (no retrieval needed).",
    )
    args = parser.parse_args()

    if not args.skip_factual and collection_count() == 0:
        print(
            "No Chroma index found. Run scripts/build_corpus.py --skip-fetch first, "
            "or pass --skip-factual.",
            file=sys.stderr,
        )
        return 1

    passed = 0
    failed = 0
    for case in load_eval_queries():
        if args.skip_factual and case["category"] == "factual":
            continue
        try:
            response = process_chat(case["query"])
            assert_eval_expectation(response, case["expect"])
            print(f"PASS  {case['id']}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL  {case['id']}: {exc}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
