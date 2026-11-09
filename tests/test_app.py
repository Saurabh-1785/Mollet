"""End-to-end flows against the offline mock gateway (documented Otari shapes)."""

import json

import httpx
import pytest

from mollet import grader, hints, problems
from mollet.otari import Otari, OtariError

BUGGY = 'def count_vowels(text):\n    n = 0\n    for ch in text:\n        if ch in "aeiou":\n            n += 1\n    return n\n'
FIXED = 'def count_vowels(text):\n    return sum(1 for ch in text.lower() if ch in "aeiou")\n'


def hint(client, sid="student_001", pid="count-vowels", q="stuck", code=""):
    return client.post("/api/hint", json={"student_id": sid, "problem_id": pid, "question": q, "code": code})


def test_pages_render(client):
    for path in ["/learn/student_001/count-vowels", "/teacher", "/status"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "Mollet" in r.text
    assert client.get("/learn/nobody/count-vowels").status_code == 404
    assert client.get("/learn/student_001/nope").status_code == 404


def test_hidden_tests_never_reach_browser(client):
    r = client.get("/learn/student_001/count-vowels")
    assert "AEIOU aeiou" not in r.text  # a hidden test input


def test_buggy_then_fixed_submission(client):
    r = client.post("/api/submit", json={"student_id": "student_001", "problem_id": "count-vowels", "code": BUGGY})
    d = r.json()
    assert r.status_code == 200
    assert d["passed"] is False and d["passed_count"] == 3 and d["total"] == 5
    assert d["mistake"]
    r = client.post("/api/submit", json={"student_id": "student_001", "problem_id": "count-vowels", "code": FIXED})
    d = r.json()
    assert d["passed"] is True and d["passed_count"] == 5
    assert d["independence"]["score"] == 100  # solved with no hints


def test_syntax_error_and_timeout(client):
    d = client.post("/api/submit", json={"student_id": "student_001", "problem_id": "count-vowels",
                                         "code": "def count_vowels(t)\n  return 0"}).json()
    assert d["load_error"]["type"] == "SyntaxError"
    d = client.post("/api/submit", json={"student_id": "student_001", "problem_id": "count-vowels",
                                         "code": "def count_vowels(t):\n  while True: pass"}).json()
    assert d["passed"] is False and d["load_error"]["type"] == "Timeout"


def test_type_strictness():
    p = problems.get("is-palindrome")
    mark = "__M__"
    code = grader.build_harness(p, "def is_palindrome(t):\n    return 1\n", mark)
    import subprocess, sys
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True).stdout
    run = grader.parse_run(out, "", mark, len(p.hidden_tests), None)
    assert not run.passed  # 1 is not True


def test_ladder_climbs_in_order_and_prices(client):
    levels = []
    for _ in range(5):
        r = hint(client)
        assert r.status_code == 200, r.text
        h = r.json()["hint"]
        levels.append(h["level"])
        assert h["cost_usd"] > 0
        assert h["debug"]["model_served"]
    assert levels == [1, 2, 3, 4, 5]
    r = hint(client)
    assert r.status_code == 409


def test_level1_uses_web_search_and_shows_docs_link(client):
    h = hint(client).json()["hint"]
    assert h["sources"] and h["sources"][0]["url"].startswith("https://docs.python.org")
    assert any(t["type"] == "web_search" for t in h["debug"]["tool_calls"])


def test_wallets_are_independent_and_drain(client):
    before_b = client.get("/api/wallet/student_002").json()["spend_usd"]
    status = []
    for pid in ["count-vowels"] * 5 + ["fizzbuzz"] * 5:
        r = hint(client, pid=pid)
        status.append(r.status_code)
        if r.status_code == 403:
            err = r.json()["error"]
            assert err["kind"] == "wallet_empty"
            assert err["otari"]["code"] == "budget_exceeded" and err["otari"]["scope"] == "user"
            break
    assert 403 in status
    assert client.get("/api/wallet/student_002").json()["spend_usd"] == before_b
    # Grading is billed to the class, so an empty wallet can still submit.
    r = client.post("/api/submit", json={"student_id": "student_001", "problem_id": "count-vowels", "code": FIXED})
    assert r.status_code == 200 and r.json()["passed"]


def test_guardrail_block_message(client):
    r = hint(client, sid="student_003", q="text me on +44 7700 900123 please")
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["kind"] == "guardrail" and err["otari"]["code"] == "guardrail_violation"
    refusals = client.get("/api/class").json()["refusals"]
    assert refusals[0]["kind"] == "guardrail_violation"


def test_request_sends_user_guardrails_and_metadata(client):
    from mollet.main import app

    hint(client, sid="student_002")
    calls = app.state.otari._client._transport.calls
    chat = [c for c in calls if c["path"] == "/chat/completions"][-1]["body"]
    assert chat["user"] == "student_002"
    assert chat["guardrails"] == [{"profile": "prompt-injection", "mode": "block"}]
    assert chat["metadata"]["role"] == "hint"
    assert chat["tools"] == [{"type": "otari_web_search", "max_uses": 1}]


def test_class_and_status_endpoints(client):
    hint(client)
    d = client.get("/api/class").json()
    assert d["class_budget"]["available"]
    assert {s["id"] for s in d["students"]} >= {"student_001", "student_002"}
    s = client.get("/api/status").json()
    assert s["mock"] is True and s["probes"]["end_user_budgets"]["ok"]


# --- app rule: never the full answer ---------------------------------------------


def test_heuristic_leak_rules():
    p = problems.get("count-vowels")
    full = "Try this:\n```python\ndef count_vowels(text):\n    return sum(c in 'aeiou' for c in text.lower())\n```"
    assert hints.heuristic_leak(full, p, 2)
    assert hints.heuristic_leak("```\nx = 1\ny = 2\n```", p, 3)
    assert hints.heuristic_leak("```python\ndef count_vowels(text):\n    n = 0\n    return n\n```", p, 4)
    assert not hints.heuristic_leak("```\ndef count_vowels(text):\n    n = ___\n    return ___\n```", p, 4)
    assert not hints.heuristic_leak("Use a `for` loop and a counter.", p, 2)
    assert "code removed" in hints.strip_code(full)


@pytest.mark.anyio
async def test_leaky_hint_is_rewritten():
    """A hint whose code passes the hidden tests is caught and rewritten."""
    p = problems.get("count-vowels")
    replies = [
        "```python\ndef count_vowels(text):\n    return sum(c in 'aeiou' for c in text.lower())\n```",
        "Think about what `.lower()` does to each letter.",
    ]
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}")
        if path.endswith("/chat/completions"):
            seen.append(body)
            text = replies[min(len(seen) - 1, 1)]
            return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                             "usage": {"cost_usd": "0.000500"}},
                                  headers={"Otari-Model": "m", "Otari-Fallback": "false"})
        if path.endswith("/code/execute"):
            import subprocess, sys
            p_ = subprocess.run([sys.executable, "-I", "-c", body["code"]], capture_output=True, text=True, timeout=10)
            return httpx.Response(200, json={"stdout": p_.stdout, "stderr": p_.stderr, "return_code": p_.returncode})
        return httpx.Response(404, json={})

    from mollet import db
    db.init()
    o = Otari(transport=httpx.MockTransport(handler))
    out = await hints.request_hint(o, student_id="student_001", problem=p, level=5, question="", code="")
    await o.aclose()
    assert len(seen) == 2
    assert "def count_vowels" not in out.text
    assert out.debug["leak_check"] != "clean"
    assert out.cost_usd == pytest.approx(0.001)


@pytest.mark.anyio
async def test_error_parsing():
    def handler(request):
        return httpx.Response(403, json={"detail": "End user x has exceeded budget limit", "code": "budget_exceeded"},
                              headers={"Otari-Error-Code": "budget_exceeded", "Otari-Budget-Scope": "user",
                                       "Retry-After": "3600"})

    o = Otari(transport=httpx.MockTransport(handler))
    with pytest.raises(OtariError) as ei:
        await o.chat(model="m", messages=[{"role": "user", "content": "hi"}], user="x")
    await o.aclose()
    e = ei.value
    assert e.is_budget and e.scope == "user" and e.retry_after == 3600


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_hint_survives_disabled_web_search():
    """If the workspace refuses the search tool, rung 1 is still served without it."""
    p = problems.get("fizzbuzz")
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        bodies.append(body)
        if body.get("tools"):
            return httpx.Response(403, json={"detail": "web search is disabled", "code": "tool_not_allowed"},
                                  headers={"Otari-Error-Code": "tool_not_allowed"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Think about `%`."}}],
                                         "usage": {"cost_usd": "0.0001"}})

    from mollet import db
    db.init()
    o = Otari(transport=httpx.MockTransport(handler))
    out = await hints.request_hint(o, student_id="student_003", problem=p, level=1, question="", code="")
    await o.aclose()
    assert out.text == "Think about `%`." and len(bodies) == 2 and "tools skipped" in out.debug["mcp"]


@pytest.mark.anyio
async def test_guardrail_code_nested_in_detail():
    """Live Otari shape: no Otari-Error-Code header, code inside `detail`."""
    def handler(request):
        return httpx.Response(403, json={"detail": {"message": "Request blocked by guardrail policy.",
                                                    "code": "guardrail_violation",
                                                    "guardrails": [{"profile": "mollet-pii", "score": 0.9}]}})

    o = Otari(transport=httpx.MockTransport(handler))
    with pytest.raises(OtariError) as ei:
        await o.chat(model="m", messages=[{"role": "user", "content": "hi"}])
    await o.aclose()
    assert ei.value.is_guardrail and ei.value.detail == "Request blocked by guardrail policy."


@pytest.mark.anyio
async def test_budget_refusal_is_never_retried_around():
    p = problems.get("fizzbuzz")
    n = []

    def handler(request):
        n.append(1)
        return httpx.Response(403, json={"detail": "x", "code": "budget_exceeded"},
                              headers={"Otari-Error-Code": "budget_exceeded", "Otari-Budget-Scope": "user"})

    o = Otari(transport=httpx.MockTransport(handler))
    with pytest.raises(OtariError):
        await hints.request_hint(o, student_id="student_003", problem=p, level=1, question="", code="")
    await o.aclose()
    assert len(n) == 1


@pytest.mark.anyio
async def test_network_error_becomes_otari_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    o = Otari(transport=httpx.MockTransport(handler))
    with pytest.raises(OtariError) as ei:
        await o.key_budget()
    await o.aclose()
    assert ei.value.code == "gateway_unreachable"
