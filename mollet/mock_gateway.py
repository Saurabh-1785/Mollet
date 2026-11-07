"""An offline stand-in for the Otari gateway, for UI work and tests only.

It mimics the documented response shapes (routing headers, usage.cost_usd,
otari_tool_calls, 403 budget_exceeded / guardrail_violation) so the app can be
exercised without a key. The UI shows a MOCK banner whenever it is active.
NEVER record the demo video against it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

import httpx

from . import db
from .wallet import next_monday_utc

PRICE = {"hinter": 0.0007, "mentor": 0.0045, "grader": 0.0009}
PHONE = re.compile(r"(?:\+?\d[\s().-]?){8,}\d")


class MockGateway(httpx.AsyncBaseTransport):
    def __init__(self, wallet_usd: float = 0.02, class_usd: float = 0.50) -> None:
        self.wallet_usd = wallet_usd
        self.class_usd = class_usd
        self.spend: dict[str, float] = {}
        self.requests: dict[str, int] = {}
        self.class_spend = 0.0
        self.fail_primary = os.getenv("MOLLET_MOCK_FAIL_PRIMARY", "") == "1"
        self.calls: list[dict[str, Any]] = []  # for tests

    # --- helpers -------------------------------------------------------------------

    @staticmethod
    def _json(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
        h = {"Content-Type": "application/json", "Otari-Request-ID": f"mock-{os.urandom(4).hex()}"}
        h.update(headers or {})
        return httpx.Response(status, content=json.dumps(body).encode(), headers=h)

    def _refuse(self, code: str, detail: str, **headers: str) -> httpx.Response:
        return self._json(403, {"detail": detail, "code": code}, {"Otari-Error-Code": code, **headers})

    def _charge(self, user: str | None, usd: float) -> None:
        self.class_spend += usd
        if user:
            self.spend[user] = self.spend.get(user, 0.0) + usd
            self.requests[user] = self.requests.get(user, 0) + 1

    def _budget_gate(self, user: str | None) -> httpx.Response | None:
        if user and self.spend.get(user, 0.0) >= self.wallet_usd:
            secs = int((next_monday_utc() - datetime.now(timezone.utc)).total_seconds())
            return self._refuse("budget_exceeded", f"End user {user} has exceeded budget limit",
                                **{"Otari-Budget-Scope": "user", "Retry-After": str(secs)})
        if self.class_spend >= self.class_usd:
            return self._refuse("budget_exceeded", "Workspace has exceeded budget limit",
                                **{"Otari-Budget-Scope": "workspace"})
        return None

    # --- routes ------------------------------------------------------------------------

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content or b"{}") if request.method in {"POST", "PUT", "PATCH"} else {}
        self.calls.append({"method": request.method, "path": path, "body": body})

        if path == "/chat/completions":
            return self._chat(body)
        if path == "/code/execute":
            return self._exec(body)
        if path == "/end-users" and request.method == "GET":
            ext = request.url.params.get("external_id")
            users = [ext] if ext else list(self.spend)
            return self._json(200, [self._eu(u) for u in users if u in self.spend])
        if path == "/end-users" and request.method == "PUT":
            ext = request.url.params.get("external_id")
            self.spend.setdefault(ext, 0.0)
            return self._json(201, self._eu(ext))
        if path == "/end-user-budgets":
            return self._json(200, [{"budget_id": "mock-wallet", "name": "mollet-weekly-wallet",
                                     "is_default": True, "max_budget": self.wallet_usd,
                                     "end_user_count": len(self.spend), "blocked_end_user_count": 0}])
        if path == "/key/budget":
            rem = max(0.0, self.class_usd - self.class_spend)
            return self._json(200, {"budgets_enforced": True, "remaining_usd": rem, "limits": [
                {"scope": "workspace", "provider": None, "resets_at": next_monday_utc().isoformat(),
                 "limit_usd": None, "used_usd": None, "remaining_usd": rem}]})
        if path == "/tools":
            return self._json(200, {"data": [
                {"type": "otari_code_execution", "available": True},
                {"type": "otari_web_search", "available": True},
                {"type": "otari_web_fetch", "available": False, "reason": "workspace_disabled"}]})
        if path == "/tool-settings/guardrails/profiles":
            return self._json(200, {"available": True, "profiles": [
                {"profile": "prompt-injection", "guardrail": "injec_guard"},
                {"profile": "pii", "guardrail": "presidio"}]})
        if path == "/models":
            return self._json(200, {"data": [{"id": "mock:hinter"}, {"id": "mock:grader"}]})
        return self._json(404, {"detail": f"mock: no route {path}"})

    def _eu(self, user: str) -> dict[str, Any]:
        return {"user_id": f"u-{user}", "external_id": user, "owner_user_id": "svc",
                "budget_id": "mock-wallet", "blocked": False, "spend": round(self.spend.get(user, 0), 6),
                "reserved": 0, "current_tokens": 0, "current_requests": self.requests.get(user, 0),
                "budget_started_at": None, "next_budget_reset_at": next_monday_utc().isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()}

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        user = body.get("user")
        refused = self._budget_gate(user)
        if refused:
            return refused
        user_text = " ".join(m.get("content", "") for m in body["messages"] if m["role"] == "user")
        question = user_text.split("Student's question:")[-1]
        if PHONE.search(question):  # stands in for an org-mandated PII guardrail
            return self._refuse("guardrail_violation", "Input flagged by guardrail 'pii'")
        system = body["messages"][0]["content"]
        role = (body.get("metadata") or {}).get("role", "hint")
        tier = "grader" if role == "grader" else ("mentor" if "mentor" in body["model"] else "hinter")
        calls: list[dict[str, Any]] = []
        hist: dict[str, Any] = {}
        m = re.search(r"Rung (\d)", system)
        level = int(m.group(1)) if m else 0
        if role == "grader":
            failed = '"passed": false' in user_text or '"load_error": {' in user_text
            content = json.dumps({"feedback": "Look at the first failing case: what does your loop do "
                                  "with upper-case letters?" if failed else "All tests pass. Clean loop!",
                                  "mistake": "forgot upper-case letters" if failed else ""})
            if body.get("tools"):
                calls.append({"id": "otari_ci_mock", "type": "code_execution", "status": "completed",
                              "code": "print(count_vowels('A'))", "stdout": "0\n", "stderr": "", "exit_code": 0})
        else:
            for t in body.get("tools") or []:
                if t.get("type") == "otari_web_search":
                    calls.append({"id": "otari_ws_mock", "type": "web_search", "status": "completed",
                                  "query": "python docs for loops", "sources": [
                                      {"url": "https://docs.python.org/3/tutorial/controlflow.html#for-statements",
                                       "title": "4. More Control Flow Tools — for Statements", "published_date": None}]})
            for sid in body.get("mcp_server_ids") or []:
                sid_user = re.search(r'student_id="([^"]+)"', system)
                hist = db.history(sid_user.group(1)) if sid_user else {}
                calls.append({"id": "otari_mcp_mock", "type": "mcp", "status": "completed",
                              "server": "mollet-classroom", "name": "get_student_history",
                              "output": json.dumps(hist)[:300]})
            last = (hist.get("recent_mistakes") or [{}])[0].get("mistake") if body.get("mcp_server_ids") else None
            recall = f"Last time you {last}; watch for that here. " if last else ""
            content = {
                1: "You need a **for loop** over the characters of the string. "
                   "See [for statements](https://docs.python.org/3/tutorial/controlflow.html#for-statements).",
                2: recall + "A loop can visit each item in turn. For example, counting even numbers in a "
                   "list means checking each number and adding 1 to a counter when it matches.",
                3: recall + "1. Start a counter at 0.\n2. Visit each character.\n3. Decide if it belongs "
                   "to the set you care about (think about case).\n4. Return the counter.",
                4: recall + "```\ncounter = ___\nfor each ch in text:\n    if ___:\n        counter = ___\nreturn ___\n```",
                5: recall + "The hard part is the membership test. Try `ch.lower() in \"aeiou\"` on a "
                   "single letter first, e.g. `'E'.lower() in 'aeiou'` is True.",
            }.get(level, "Keep going!")
        served = body["model"]
        headers = {"Otari-Model": f"{tier}-primary", "Otari-Provider": "mock", "Otari-Attempt-Count": "1",
                   "Otari-Fallback": "false"}
        if self.fail_primary and tier == "hinter":
            headers.update({"Otari-Model": "hinter-backup", "Otari-Attempt-Count": "2", "Otari-Fallback": "true"})
        guard = [{"profile": g["profile"], "mode": g.get("mode", "monitor"), "valid": True, "score": None,
                  "status": "evaluated"} for g in body.get("guardrails") or []]
        if guard:
            headers["Otari-Guardrails"] = json.dumps(guard)
        cost = PRICE[tier] * (1.6 if level == 5 else 1.0)
        self._charge(user, cost)
        return self._json(200, {
            "id": "chatcmpl-mock", "object": "chat.completion", "model": served,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 120, "total_tokens": 520,
                      "cost_usd": f"{cost:.6f}", "pricing_source": "defaults"},
            "otari_tool_calls": calls,
        }, headers)

    def _exec(self, body: dict[str, Any]) -> httpx.Response:
        refused = self._budget_gate(body.get("user"))
        if refused:
            return refused
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "main.py")
            with open(path, "w") as f:
                f.write(body["code"])
            try:
                p = subprocess.run([sys.executable, "-I", path], capture_output=True, text=True,
                                   timeout=min(int(body.get("timeout_seconds") or 10), 10), cwd=d)
                out, err, rc = p.stdout, p.stderr, p.returncode
            except subprocess.TimeoutExpired:
                out, err, rc = "", "Execution timed out", 124
        self._charge(body.get("user"), 0.0002)
        return self._json(200, {"object": "code_execution.result", "stdout": out, "stderr": err,
                                "return_code": rc, "files": []})
