"""Run one user journey: fresh app + database, real browser, an agent policy,
then data-level checks on what the journey left behind."""
from __future__ import annotations

import socket
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import uvicorn
import yaml
from playwright.sync_api import sync_playwright

from app.main import create_app

from .policies import GuidedPolicy, LLMPolicy
from .tools import BrowserTools

JOURNEYS_DIR = Path(__file__).parent / "journeys"
MAX_STEPS = 30


@dataclass
class Journey:
    name: str
    persona: str
    goal: str
    user_email: str
    steps: list[dict]
    checks: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Journey":
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(name=path.stem, **d)


def load_journeys(directory: Path = JOURNEYS_DIR) -> list[Journey]:
    return [Journey.load(p) for p in sorted(directory.glob("*.yml"))]


@contextmanager
def running_app(bugs: set[str]):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "app.db"
        app = create_app(db_path, bugs)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.02)
        try:
            yield f"http://127.0.0.1:{port}", db_path
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def run_checks(db_path: Path, journey: Journey, tools: BrowserTools) -> list[dict]:
    con = sqlite3.connect(db_path)
    uid = con.execute("select user_id from users where email = ?", (journey.user_email,)).fetchone()[0]
    results = [{"check": "no server errors", "passed": not tools.server_errors,
                "detail": "; ".join(tools.server_errors) or "none"}]
    for chk in journey.checks:
        if "events" in chk:
            got = dict(con.execute("select event_type, count(*) from events where user_id = ? "
                                   "group by event_type", (uid,)).fetchall())
            want = chk["events"]
            ok = all(got.get(k, 0) == v for k, v in want.items())
            results.append({"check": f"tracking events {want}", "passed": ok, "detail": f"got {got}"})
        elif "sql" in chk:
            val = con.execute(chk["sql"], {"user_id": uid}).fetchone()
            val = val[0] if val else None
            results.append({"check": chk.get("name", chk["sql"]), "passed": val == chk["equals"],
                            "detail": f"expected {chk['equals']!r}, got {val!r}"})
    con.close()
    return results


@dataclass
class JourneyResult:
    journey: str
    bugs: list[str]
    policy: str
    agent_passed: bool
    agent_summary: str
    checks: list[dict]
    trace: list[dict]
    seconds: float
    usage: dict | None = None

    @property
    def passed(self) -> bool:
        return self.agent_passed and all(c["passed"] for c in self.checks)

    def to_dict(self) -> dict:
        return {**asdict(self), "passed": self.passed}


def run_journey(journey: Journey, bugs: set[str] | None = None, policy: str = "guided",
                model: str | None = None, completion=None, headless: bool = True) -> JourneyResult:
    bugs = set(bugs or ())
    t0 = time.perf_counter()
    with running_app(bugs) as (base_url, db_path), sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        tools = BrowserTools(page)
        page.goto(base_url + "/")
        if policy == "guided":
            agent = GuidedPolicy(journey.steps)
        else:
            agent = LLMPolicy(model or "gpt-4o-mini", journey.persona,
                              f"{journey.goal} Sign in with {journey.user_email}.", completion)
        trace, last, verdict = [], None, (False, f"stopped after {MAX_STEPS} steps")
        for _ in range(MAX_STEPS):
            call = agent.next(last)
            if call.name == "finish":
                verdict = (bool(call.args.get("passed")), str(call.args.get("summary", "")))
                trace.append({"tool": "finish", "args": call.args})
                break
            last = tools.call(call.name, call.args)
            trace.append({"tool": call.name, "args": call.args, "result": last[:300]})
        checks = run_checks(db_path, journey, tools)
        browser.close()
    return JourneyResult(journey.name, sorted(bugs), policy, verdict[0], verdict[1], checks,
                         trace, round(time.perf_counter() - t0, 2),
                         getattr(agent, "usage", None))
