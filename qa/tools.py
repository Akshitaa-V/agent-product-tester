"""Browser tools the agent can call. Each returns a short text result,
the same thing an LLM sees after a tool call."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "snapshot",
        "description": "Return the accessibility tree of the current page (roles, names, text).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click an element by its ARIA role and accessible name, e.g. role=button name='Sign in'.",
        "parameters": {"type": "object", "required": ["role", "name"], "properties": {
            "role": {"type": "string", "enum": ["button", "link"]},
            "name": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "fill",
        "description": "Type text into the form field with this visible label, replacing what is there.",
        "parameters": {"type": "object", "required": ["label", "text"], "properties": {
            "label": {"type": "string"}, "text": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "check_text",
        "description": "Check whether some text is visible on the current page.",
        "parameters": {"type": "object", "required": ["text"], "properties": {
            "text": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "End the test. passed=true only if the goal was reached and nothing looked broken.",
        "parameters": {"type": "object", "required": ["passed", "summary"], "properties": {
            "passed": {"type": "boolean"}, "summary": {"type": "string"}}}}},
]


@dataclass
class BrowserTools:
    page: Page
    timeout_ms: int = 3000
    server_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.page.on("response", lambda r: r.status >= 500 and self.server_errors.append(
            f"{r.status} {r.request.method} {r.url}"))
        self.page.on("console", lambda m: m.type == "error" and self.console_errors.append(m.text))

    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return f"ERROR unknown tool {name!r}"
        try:
            return fn(**args)
        except PWTimeout:
            return f"ERROR {name} timed out: element not found or not actionable"
        except TypeError as exc:
            return f"ERROR bad arguments for {name}: {exc}"

    def _status(self) -> str:
        errs = f" | server errors so far: {len(self.server_errors)}" if self.server_errors else ""
        return f"now on {self.page.url.split('//', 1)[-1].split('/', 1)[-1] or '/'} ('{self.page.title()}'){errs}"

    def tool_snapshot(self) -> str:
        return self.page.locator("body").aria_snapshot()

    def tool_click(self, role: str, name: str) -> str:
        loc = self.page.get_by_role(role, name=name, exact=True)
        if loc.count() == 0:
            return f"ERROR no {role} named {name!r} on this page"
        if loc.count() > 1:
            return f"ERROR {loc.count()} elements match {role} {name!r}; be more specific"
        loc.click(timeout=self.timeout_ms)
        self.page.wait_for_load_state()
        return f"clicked {role} {name!r}; {self._status()}"

    def tool_fill(self, label: str, text: str) -> str:
        loc = self.page.get_by_label(label, exact=True)
        if loc.count() != 1:
            return f"ERROR found {loc.count()} fields labelled {label!r}"
        loc.fill(text, timeout=self.timeout_ms)
        return f"filled {label!r} with {len(text)} characters"

    def tool_check_text(self, text: str) -> str:
        body = self.page.locator("body").inner_text()
        found = re.sub(r"\s+", " ", text) in re.sub(r"\s+", " ", body)
        return f"{'FOUND' if found else 'NOT FOUND'}: {text!r}"
