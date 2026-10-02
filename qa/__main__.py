"""python -m qa run | matrix | llm

run     all journeys against the app (optionally with --bug flags)
matrix  every known bug on its own: which journeys catch it, plus a clean run
llm     one journey driven by an LLM through tool calling (needs an API key)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.main import KNOWN_BUGS

from .runner import load_journeys, run_journey

REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _line(r) -> str:
    failed = [c["check"] for c in r.checks if not c["passed"]]
    why = r.agent_summary if not r.agent_passed else "; ".join(failed)
    return f"{'PASS' if r.passed else 'FAIL'}  {r.journey:<32} {r.seconds:>5.2f}s  {why if not r.passed else ''}"


def cmd_run(bugs: set[str]) -> list:
    results = [run_journey(j, bugs) for j in load_journeys()]
    for r in results:
        print(_line(r))
    return results


def cmd_matrix() -> dict:
    journeys = load_journeys()
    t0 = time.perf_counter()
    clean = [run_journey(j) for j in journeys]
    rows = []
    for bug, desc in KNOWN_BUGS.items():
        res = [run_journey(j, {bug}) for j in journeys]
        caught_by = [r.journey for r in res if not r.passed]
        evidence = next((r for r in res if not r.passed), None)
        rows.append({"bug": bug, "description": desc, "caught": bool(caught_by),
                     "caught_by": caught_by,
                     "evidence": (evidence.agent_summary if evidence and not evidence.agent_passed
                                  else "; ".join(f"{c['check']}: {c['detail']}"
                                                 for c in evidence.checks if not c["passed"]))
                     if evidence else ""})
    summary = {
        "journeys": len(journeys),
        "clean_runs_passed": sum(r.passed for r in clean),
        "bugs_planted": len(KNOWN_BUGS),
        "bugs_caught": sum(r["caught"] for r in rows),
        "browser_runs": len(journeys) * (len(KNOWN_BUGS) + 1),
        "seconds": round(time.perf_counter() - t0, 1),
        "bugs": rows,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "bug_matrix.json").write_text(json.dumps(summary, indent=2))
    md = [f"# Bug matrix\n",
          f"{summary['clean_runs_passed']}/{summary['journeys']} journeys pass on the clean app. "
          f"{summary['bugs_caught']}/{summary['bugs_planted']} planted bugs caught "
          f"in {summary['browser_runs']} browser runs ({summary['seconds']} s).\n",
          "| Bug | Caught by | Evidence |", "|---|---|---|"]
    for r in rows:
        md.append(f"| {r['description']} | {', '.join(r['caught_by']) or 'not caught'} | "
                  f"{r['evidence'].replace('|', '/')[:160]} |")
    (REPORTS / "bug_matrix.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(prog="qa")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--bug", action="append", default=[], choices=sorted(KNOWN_BUGS))
    sub.add_parser("matrix")
    l = sub.add_parser("llm")
    l.add_argument("journey", help="journey file name without .yml, e.g. 01_complete_practice_session")
    l.add_argument("--model", default="gpt-4o-mini", help="any LiteLLM model string")
    l.add_argument("--bug", action="append", default=[], choices=sorted(KNOWN_BUGS))
    l.add_argument("--headed", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "run":
        cmd_run(set(a.bug))
    elif a.cmd == "matrix":
        cmd_matrix()
    else:
        j = next(j for j in load_journeys() if j.name == a.journey)
        res = run_journey(j, set(a.bug), policy="llm", model=a.model, headless=not a.headed)
        for step in res.trace:
            print(f"- {step['tool']}({json.dumps(step['args'])[:120]})")
        print(_line(res), res.usage)


if __name__ == "__main__":
    main()
