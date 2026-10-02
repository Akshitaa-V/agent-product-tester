"""Every journey passes on the clean app, and every planted bug is caught
by the journey written for it, through a real browser."""
import pytest

from app.main import KNOWN_BUGS
from qa.runner import load_journeys, run_journey

JOURNEYS = {j.name: j for j in load_journeys()}

EXPECTED_CATCH = {
    "goal_no_validation": "03_invalid_goal_rejected",
    "feedback_event_missing": "01_complete_practice_session",
    "progress_counts_abandoned": "04_abandon_session",
    "long_answer_crash": "05_long_answer",
    "double_completed_event": "01_complete_practice_session",
}


@pytest.mark.parametrize("name", sorted(JOURNEYS))
def test_journey_passes_on_clean_app(name):
    r = run_journey(JOURNEYS[name])
    assert r.passed, r.to_dict()


def test_every_known_bug_has_a_catching_journey():
    assert EXPECTED_CATCH.keys() == KNOWN_BUGS.keys()


@pytest.mark.parametrize("bug, journey", sorted(EXPECTED_CATCH.items()))
def test_planted_bug_is_caught(bug, journey):
    r = run_journey(JOURNEYS[journey], {bug})
    assert not r.passed


def test_crash_is_reported_as_server_error():
    r = run_journey(JOURNEYS["05_long_answer"], {"long_answer_crash"})
    server = next(c for c in r.checks if c["check"] == "no server errors")
    assert not server["passed"] and "500 POST" in server["detail"]
