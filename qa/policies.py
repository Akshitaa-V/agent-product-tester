"""Policies decide the next tool call.

GuidedPolicy follows the steps written in a journey file, resolving every
element through the same role/name/label tools an LLM would use. It is
deterministic, so it runs in CI without an API key.

LLMPolicy gives a model the persona, the goal and the tool schemas, and lets
it decide what to click (any provider LiteLLM supports). It needs an API key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .tools import TOOL_SCHEMAS


@dataclass
class ToolCall:
    name: str
    args: dict
    call_id: str = ""


class GuidedPolicy:
    def __init__(self, steps: list[dict]):
        self.steps = list(steps)
        self.i = 0
        self.failure: str | None = None

    def next(self, last_result: str | None) -> ToolCall:
        if last_result is not None:
            if last_result.startswith("ERROR") or last_result.startswith("NOT FOUND"):
                self.failure = f"step {self.i}: {last_result}"
        if self.failure:
            return ToolCall("finish", {"passed": False, "summary": self.failure})
        if self.i >= len(self.steps):
            return ToolCall("finish", {"passed": True, "summary": "all steps done"})
        step = self.steps[self.i]
        self.i += 1
        (kind, arg), = step.items()
        if kind == "expect":
            return ToolCall("check_text", {"text": arg})
        return ToolCall(kind, dict(arg))


SYSTEM_PROMPT = """You are testing a web app as a real user would.
Persona: {persona}
Goal: {goal}
Use the tools to act in the browser. Start with snapshot to see the page.
Work only through what is visible; do not guess URLs.
If something looks broken (an error page, a missing confirmation, a value that is wrong),
call finish with passed=false and describe what you saw. Otherwise finish with passed=true
once the goal is reached."""


class LLMPolicy:
    def __init__(self, model: str, persona: str, goal: str,
                 completion: Callable | None = None, temperature: float = 0.0):
        if completion is None:
            from litellm import completion  # imported lazily: CI never needs it
        self.completion = completion
        self.model = model
        self.temperature = temperature
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(persona=persona, goal=goal)},
            {"role": "user", "content": "Begin the test."},
        ]
        self._pending: list[ToolCall] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def next(self, last_result: str | None) -> ToolCall:
        if last_result is not None and self._last_id is not None:
            self.messages.append({"role": "tool", "tool_call_id": self._last_id, "content": last_result})
        if not self._pending:
            resp = self.completion(model=self.model, messages=self.messages, tools=TOOL_SCHEMAS,
                                   tool_choice="required", temperature=self.temperature)
            msg = resp.choices[0].message
            usage = getattr(resp, "usage", None)
            if usage:
                self.usage["prompt_tokens"] += usage.prompt_tokens or 0
                self.usage["completion_tokens"] += usage.completion_tokens or 0
            calls = msg.tool_calls or []
            self.messages.append({"role": "assistant", "content": msg.content or "",
                                  "tool_calls": [{"id": c.id, "type": "function",
                                                  "function": {"name": c.function.name,
                                                               "arguments": c.function.arguments}}
                                                 for c in calls]})
            if not calls:
                return ToolCall("finish", {"passed": False, "summary": "model returned no tool call"})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": c.function.arguments}
                self._pending.append(ToolCall(c.function.name, args, c.id))
        call = self._pending.pop(0)
        self._last_id = call.call_id
        return call

    _last_id: str | None = None
