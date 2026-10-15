from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checker import RuleError, run_checks
from .report import write_html, write_junit
from .simulator import FAULTS, simulate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cantestreport",
                                     description="Turn CAN logs into requirement test reports.")
    sub = parser.add_subparsers(dest="command", required=True)

    sim = sub.add_parser("simulate", help="Create a synthetic CAN log (no hardware needed).")
    sim.add_argument("--dbc", required=True)
    sim.add_argument("--out", required=True)
    sim.add_argument("--duration", type=float, default=10.0)
    sim.add_argument("--fault", action="append", default=[], choices=sorted(FAULTS),
                     help="Inject a fault. Can be used more than once.")
    sim.add_argument("--seed", type=int, default=1)

    run = sub.add_parser("run", help="Check a CAN log against the requirements.")
    run.add_argument("--log", required=True)
    run.add_argument("--dbc", required=True)
    run.add_argument("--rules", required=True)
    run.add_argument("--html", default="reports/report.html")
    run.add_argument("--junit", default=None)

    args = parser.parse_args(argv)

    if args.command == "simulate":
        count = simulate(args.dbc, args.out, args.duration, args.fault, args.seed)
        print(f"Wrote {count} frames to {args.out}")
        return 0

    try:
        results, log = run_checks(args.log, args.dbc, args.rules)
    except (RuleError, OSError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    name = Path(args.log).name
    write_html(results, log, name, args.html)
    if args.junit:
        write_junit(results, name, args.junit)
    for r in results:
        print(f"{r.status:4}  {r.rule_id}  {r.summary}")
    failed = sum(r.status == "FAIL" for r in results)
    print(f"\n{len(results) - failed} passed, {failed} failed. Report: {args.html}")
    return 1 if failed else 0
