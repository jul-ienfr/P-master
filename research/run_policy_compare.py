"""Run offline policy comparison against replay fixtures/corpora."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.policy_compare import build_policy_compare_summary, load_policy_compare_corpus  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare offline policies over replay fixtures/corpora")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON fixture/corpus files or directories, including review_pack exports and frontend envelopes",
    )
    parser.add_argument("--baseline", dest="baseline_policy", default=None, help="Baseline policy name")
    parser.add_argument("--challenger", dest="challenger_policy", default=None, help="Challenger policy name")
    parser.add_argument(
        "--list-policies",
        action="store_true",
        help="Print discovered policy names before writing the summary from fixtures, bundles, or review_pack inputs",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "research" / "results" / "policy_compare_summary.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()

    records = load_policy_compare_corpus(args.inputs)
    payload = build_policy_compare_summary(
        records,
        baseline_policy=args.baseline_policy,
        challenger_policy=args.challenger_policy,
    )
    if args.list_policies:
        print("policies=" + ",".join(payload.get("available_policies", [])))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
