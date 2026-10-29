#!/usr/bin/env python3
"""Independent Phase 4 verifier.

Usage:
    .venv/bin/python tools/verify_phase4.py [outputs/phase4]

Recalculates travel, cycle time, throughput, percentage changes, 2x2 effects, inventory
conservation, split integrity, regime counts, headroom and provenance hashes from the raw
artifacts. Writes ``verification.json`` beside them and exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.verify import verify_phase4_artifacts  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(prog="verify_phase4")
    ap.add_argument("phase4_dir", nargs="?", default=str(ROOT / "outputs" / "phase4"))
    args = ap.parse_args()

    report = verify_phase4_artifacts(Path(args.phase4_dir))
    path = Path(args.phase4_dir) / "verification.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"checks: {report['n_checks']}  failed: {report['n_failed']}")
    for check in report["checks"]:
        status = "ok  " if check["passed"] else "FAIL"
        print(f"  {status} {check['name']}")
        if not check["passed"] and check["detail"]:
            print(f"       {check['detail']}")
    print(f"report: {path}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
