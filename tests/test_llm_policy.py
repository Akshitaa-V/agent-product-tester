"""The LLM policy loop, driven by a scripted fake model that speaks the
OpenAI/LiteLLM tool-calling format. No API key or network needed."""
import json
from types import SimpleNamespace as NS

from qa.runner import load_journeys, run_journey

JOURNEYS = {j.name: j for j in load_journeys()}


def fake_model(script):
    """Returns one scripted tool call per model turn and records what the model saw."""
    seen = []

    def completion(model, messages, tools, **kw):
        seen.append([m.copy() for m in messages])
        name, args = script[len(seen) - 1]
        call = NS(id=f"call_{len(seen)}", function=NS(name=name, arguments=json.dumps(args)
                                                      if isinstance(args, dict) else args))
        return NS(choices=[NS(message=NS(content="", tool_calls=[call]))],
                  usage=NS(prompt_tokens=100, completion_tokens=10))

    completion.seen = seen
    return completion


GOAL_SCRIPT = [
    ("snapshot", {}),
    ("fill", {"label": "Work email", "text": "tom@demo.test"}),
    ("click", {"role": "button", "name": "Sign in"}),
    ("click", {"role": "link", "name": "Set weekly goal"}),
    ("fill", {"label": "Sessions per week", "text": "3"}),
    ("click", {"role": "button", "name": "Save goal"}),
    ("check_text", {"text": "0 of 3 sessions done"}),
    ("finish", {"passed": True, "summary": "goal saved and shown"}),
]


def test_llm_policy_completes_journey():
    model = fake_model(GOAL_SCRIPT)
    r = run_journey(JOURNEYS["02_set_weekly_goal"], policy="llm", model="fake", completion=model)
    assert r.passed, r.to_dict()
    assert r.usage == {"prompt_tokens": 800, "completion_tokens": 80}
    # every tool result went back to the model with the matching tool_call_id
    last = model.seen[-1]
    tool_msgs = [m for m in last if m["role"] == "tool"]
    assert len(tool_msgs) == 7 and tool_msgs[0]["tool_call_id"] == "call_1"
    assert "Sign in" in tool_msgs[0]["content"]          # the snapshot it looked at


def test_tool_errors_go_back_to_the_model():
    script = [("click", {"role": "button", "name": "Log in"}),          # wrong name
              ("click", "{not json"),                                   # malformed args
              *GOAL_SCRIPT[1:]]
    model = fake_model(script)
    r = run_journey(JOURNEYS["02_set_weekly_goal"], policy="llm", model="fake", completion=model)
    assert r.passed
    results = [t["result"] for t in r.trace[:2]]
    assert results[0].startswith("ERROR no button named 'Log in'")
    assert results[1].startswith("ERROR bad arguments")


def test_data_checks_overrule_an_optimistic_agent():
    """The agent says it passed, but the tracking data says otherwise."""
    script = GOAL_SCRIPT[:3] + [("finish", {"passed": True, "summary": "looks fine"})]
    r = run_journey(JOURNEYS["02_set_weekly_goal"], policy="llm", model="fake",
                    completion=fake_model(script))
    assert r.agent_passed and not r.passed
