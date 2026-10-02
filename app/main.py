"""Practice app: sign in, run a practice session, get feedback, set a weekly goal.

The weekly goal is the feature shipped end to end in this repo:
data model (goals table) -> routes -> UI -> tracking event (goal_set)
-> progress on the dashboard.

`bugs` switches on known defects so the agent tester can prove it finds them.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db
from .scoring import score_answer

KNOWN_BUGS = {
    "goal_no_validation":        "Goal form accepts 0 or negative values.",
    "feedback_event_missing":    "Opening feedback does not send feedback_viewed.",
    "progress_counts_abandoned": "Weekly progress also counts abandoned sessions.",
    "long_answer_crash":         "Answers over 400 characters crash on submit.",
    "double_completed_event":    "Submitting sends session_completed twice.",
}
GOAL_MIN, GOAL_MAX = 1, 14

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def week_start(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).date()
    return f"{monday} 00:00:00"


def create_app(db_path: Path | str, bugs: set[str] | None = None) -> FastAPI:
    bugs = set(bugs or ())
    unknown = bugs - KNOWN_BUGS.keys()
    if unknown:
        raise ValueError(f"unknown bugs: {sorted(unknown)}")
    db.init(db_path)
    con = db.connect(db_path)
    app = FastAPI(title="Practice app")

    def current_user(request: Request):
        uid = request.cookies.get("uid")
        return con.execute("select * from users where user_id = ?", (uid,)).fetchone() if uid else None

    def render(request, name, status_code=200, **ctx):
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def login_required(request):
        return RedirectResponse("/", status_code=303)

    # --- sign in -----------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def signin_page(request: Request):
        return render(request, "signin.html", error=None)

    @app.post("/signin")
    def signin(request: Request, email: str = Form("")):
        user = con.execute("select * from users where email = ?", (email.strip().lower(),)).fetchone()
        if not user:
            return render(request, "signin.html", status_code=400, error="No account with that email.")
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("uid", user["user_id"], httponly=True)
        return resp

    # --- dashboard ---------------------------------------------------------
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        user = current_user(request)
        if not user:
            return login_required(request)
        statuses = ("completed", "abandoned") if "progress_counts_abandoned" in bugs else ("completed",)
        done = con.execute(
            f"select count(*) from sessions where user_id = ? and started_at >= ? "
            f"and status in ({','.join('?' * len(statuses))})",
            (user["user_id"], week_start(), *statuses)).fetchone()[0]
        goal = con.execute("select sessions_per_week from goals where user_id = ?",
                           (user["user_id"],)).fetchone()
        recent = con.execute("""
            select s.session_id, s.status, s.score, c.title from sessions s
            join scenarios c using (scenario_id) where s.user_id = ?
            order by s.started_at desc, s.rowid desc limit 5""", (user["user_id"],)).fetchall()
        scenarios = con.execute("select * from scenarios order by title").fetchall()
        return render(request, "dashboard.html", user=user, done=done,
                      goal=goal[0] if goal else None, recent=recent, scenarios=scenarios)

    # --- practice sessions -------------------------------------------------
    @app.post("/sessions")
    def start_session(request: Request, scenario_id: str = Form(...)):
        user = current_user(request)
        if not user:
            return login_required(request)
        sid = f"ses_{uuid.uuid4().hex[:10]}"
        with con:
            con.execute("insert into sessions (session_id, user_id, scenario_id, status, started_at) "
                        "values (?, ?, ?, 'started', ?)", (sid, user["user_id"], scenario_id, db.now()))
            db.track(con, user["user_id"], "session_started", sid, scenario_id)
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    def own_session(request, sid):
        user = current_user(request)
        if not user:
            return None, None
        s = con.execute("""select s.*, c.title, c.prompt, c.keywords from sessions s
                           join scenarios c using (scenario_id)
                           where session_id = ? and user_id = ?""", (sid, user["user_id"])).fetchone()
        return user, s

    @app.get("/sessions/{sid}", response_class=HTMLResponse)
    def session_page(request: Request, sid: str):
        user, s = own_session(request, sid)
        if not s:
            return login_required(request)
        if s["status"] != "started":
            return RedirectResponse("/dashboard", status_code=303)
        return render(request, "session.html", s=s, error=None, answer="")

    @app.post("/sessions/{sid}/submit")
    def submit(request: Request, sid: str, answer: str = Form("")):
        user, s = own_session(request, sid)
        if not s or s["status"] != "started":
            return RedirectResponse("/dashboard", status_code=303)
        if not answer.strip():
            return render(request, "session.html", status_code=400, s=s, answer="",
                          error="Please write an answer before submitting.")
        if "long_answer_crash" in bugs and len(answer) > 400:
            raise RuntimeError("answer column overflow")
        score, tips = score_answer(answer, json.loads(s["keywords"]))
        started = datetime.fromisoformat(s["started_at"])
        duration = int((datetime.fromisoformat(db.now()) - started).total_seconds())
        with con:
            con.execute("update sessions set status = 'completed', completed_at = ?, answer = ?, "
                        "score = ? where session_id = ?", (db.now(), answer, score, sid))
            for _ in range(2 if "double_completed_event" in bugs else 1):
                db.track(con, user["user_id"], "session_completed", sid, s["scenario_id"],
                         score=score, duration_s=duration)
        return RedirectResponse(f"/sessions/{sid}/feedback", status_code=303)

    @app.post("/sessions/{sid}/abandon")
    def abandon(request: Request, sid: str):
        user, s = own_session(request, sid)
        if s and s["status"] == "started":
            with con:
                con.execute("update sessions set status = 'abandoned' where session_id = ?", (sid,))
                db.track(con, user["user_id"], "session_abandoned", sid, s["scenario_id"])
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/sessions/{sid}/feedback", response_class=HTMLResponse)
    def feedback(request: Request, sid: str):
        user, s = own_session(request, sid)
        if not s or s["status"] != "completed":
            return RedirectResponse("/dashboard", status_code=303)
        _, tips = score_answer(s["answer"], json.loads(s["keywords"]))
        if "feedback_event_missing" not in bugs:
            with con:
                db.track(con, user["user_id"], "feedback_viewed", sid, s["scenario_id"])
        return render(request, "feedback.html", s=s, tips=tips)

    # --- weekly goal (the shipped feature) ---------------------------------
    @app.get("/goal", response_class=HTMLResponse)
    def goal_page(request: Request):
        user = current_user(request)
        if not user:
            return login_required(request)
        g = con.execute("select sessions_per_week from goals where user_id = ?",
                        (user["user_id"],)).fetchone()
        return render(request, "goal.html", value=g[0] if g else 3, error=None,
                      lo=GOAL_MIN, hi=GOAL_MAX)

    @app.post("/goal")
    def set_goal(request: Request, sessions_per_week: str = Form("")):
        user = current_user(request)
        if not user:
            return login_required(request)
        try:
            value = int(sessions_per_week)
        except ValueError:
            value = None
        valid = value is not None and GOAL_MIN <= value <= GOAL_MAX
        if "goal_no_validation" in bugs:
            valid = value is not None
        if not valid:
            return render(request, "goal.html", status_code=400, value=sessions_per_week,
                          lo=GOAL_MIN, hi=GOAL_MAX,
                          error=f"Choose a number between {GOAL_MIN} and {GOAL_MAX}.")
        with con:
            con.execute("insert into goals values (?, ?, ?) on conflict(user_id) do update "
                        "set sessions_per_week = excluded.sessions_per_week, set_at = excluded.set_at",
                        (user["user_id"], value, db.now()))
            db.track(con, user["user_id"], "goal_set", sessions_per_week=value)
        return RedirectResponse("/dashboard", status_code=303)

    return app
