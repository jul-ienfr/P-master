"""Run the extended offline RL/replay lab and persist a summary artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.rl_lab import (  # noqa: E402
    build_rl_lab_payload,
    write_rl_lab_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--solver",
        action="store_true",
        help="évalue le corpus avec le solveur natif au lieu des EV synthétiques",
    )
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--bet-sizes", type=str, default="50%")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    kwargs = {
        "solver_eval": args.solver,
        "max_iterations": args.max_iterations,
        "bet_sizes": args.bet_sizes or None,
    }
    payload = build_rl_lab_payload(**kwargs)
    output_path = write_rl_lab_payload(payload, args.output)
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
