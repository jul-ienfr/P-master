"""Run the extended offline RL/replay lab and persist a summary artifact."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.rl_lab import build_rl_lab_payload, write_rl_lab_summary  # noqa: E402


def main() -> None:
    payload = build_rl_lab_payload()
    output_path = write_rl_lab_summary()
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"saved={output_path}")


if __name__ == "__main__":
    main()
