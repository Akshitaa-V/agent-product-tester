import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    c = TestClient(create_app(tmp_path / "app.db"))
    c.db = tmp_path / "app.db"
    return c


def signin(c, email="lena@demo.test"):
    r = c.post("/signin", data={"email": email}, follow_redirects=False)
    assert r.status_code == 303
    return c


def events(c):
    import sqlite3
    con = sqlite3.connect(c.db)
    return [r[0] for r in con.execute("select event_type from events order by rowid")]


def test_unknown_email_is_refused(client):
    r = client.post("/signin", data={"email": "nobody@demo.test"})
    assert r.status_code == 400 and "No account" in r.text


def test_pages_need_sign_in(client):
    for path in ["/dashboard", "/goal"]:
        assert client.get(path, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("value, ok", [("0", False), ("1", True), ("14", True), ("15", False),
                                       ("-2", False), ("abc", False), ("", False)])
def test_goal_bounds(client, value, ok):
    signin(client)
    r = client.post("/goal", data={"sessions_per_week": value}, follow_redirects=False)
    assert (r.status_code == 303) is ok
    assert events(client).count("goal_set") == (1 if ok else 0)


def test_full_session_tracks_events_in_order(client):
    signin(client)
    r = client.post("/sessions", data={"scenario_id": "scn_price"}, follow_redirects=False)
    sid = r.headers["location"].rsplit("/", 1)[-1]
    r = client.post(f"/sessions/{sid}/submit", data={"answer": "I understand. What matters most?"})
    assert "Score:" in r.text
    assert events(client) == ["session_started", "session_completed", "feedback_viewed"]


def test_empty_answer_is_not_scored(client):
    signin(client)
    sid = client.post("/sessions", data={"scenario_id": "scn_price"},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
    r = client.post(f"/sessions/{sid}/submit", data={"answer": "   "})
    assert r.status_code == 400
    assert "session_completed" not in events(client)


def test_cannot_open_someone_elses_session(client):
    signin(client)
    sid = client.post("/sessions", data={"scenario_id": "scn_price"},
                      follow_redirects=False).headers["location"].rsplit("/", 1)[-1]
    signin(client, "tom@demo.test")
    r = client.post(f"/sessions/{sid}/submit", data={"answer": "taking over"}, follow_redirects=False)
    assert r.status_code == 303
    assert "session_completed" not in events(client)


def test_unknown_bug_flag_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path / "x.db", {"not_a_bug"})
