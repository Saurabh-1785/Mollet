"""Day-1 checks: does each Otari feature Mollet relies on work with YOUR key?

    python -m scripts.check_otari            # all checks
    python -m scripts.check_otari search mcp # just some

Spends a few tenths of a cent. Paste anything surprising into FEEDBACK.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from mollet.config import settings
from mollet.otari import Otari, OtariError

PROBE_USER = "mollet_probe_student"
GREEN, RED, YEL, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def show(ok: bool | None, name: str, msg: str) -> None:
    mark = {True: f"{GREEN}PASS{END}", False: f"{RED}FAIL{END}", None: f"{YEL}SKIP{END}"}[ok]
    print(f"{mark}  {name:<26} {msg}")


def say(m: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": m}]


async def check_models(o: Otari) -> None:
    for role, model in [("hinter", settings.hinter_model), ("mentor", settings.mentor_model),
                        ("grader", settings.grader_model)]:
        try:
            r = await o.chat(model=model, messages=say("Reply with the single word: ready"), max_tokens=10)
            show(True, f"model:{role}", f"{model} -> served by {r.model_served} via {r.provider} "
                 f"(fallback={r.fallback}, attempts={r.attempt_count}) cost ${r.cost_usd:.6f}")
        except OtariError as e:
            show(False, f"model:{role}", f"{model}: {e.status} {e.code} {e.detail[:160]}")


async def check_end_users(o: Otari) -> None:
    try:
        r = await o.chat(model=settings.hinter_model, messages=say("Say ok"), user=PROBE_USER, max_tokens=5)
        eu = await o.end_user(PROBE_USER)
        budgets = await o.end_user_budgets()
        show(bool(eu), "per-user budget",
             f"end user spend=${(eu or {}).get('spend')} budget={(eu or {}).get('budget_id')} "
             f"resets={(eu or {}).get('next_budget_reset_at')}; key budgets: "
             + ", ".join(f"{b.get('name')}=${b.get('max_budget')}" for b in budgets))
        if not budgets:
            print(f"{DIM}      -> tick 'Service key' + pick a default end-user budget when creating the key{END}")
    except OtariError as e:
        show(False, "per-user budget", f"{e.status} {e.code} {e.detail[:200]}")


async def check_key_budget(o: Otari) -> None:
    try:
        b = await o.key_budget()
        lim = [f"{l['scope']}: remaining ${l.get('remaining_usd')}" for l in b.get("limits", [])]
        show(bool(lim), "class budget", f"enforced={b.get('budgets_enforced')} " + "; ".join(lim))
    except OtariError as e:
        show(False, "class budget", f"{e.status} {e.code} {e.detail[:200]}")


async def check_code(o: Otari) -> None:
    try:
        r = await o.execute_code("import math\nprint(math.factorial(23))", timeout_s=10)
        ok = r.stdout.strip() == "25852016738884976640000"
        show(ok, "code execution (direct)", f"stdout={r.stdout.strip()!r} rc={r.return_code}")
    except OtariError as e:
        show(False, "code execution (direct)", f"{e.status} {e.code} {e.detail[:200]}")
    try:
        r = await o.chat(model=settings.grader_model, messages=say("Use the code tool to compute 23 factorial."),
                         tools=[{"type": "otari_code_execution"}], max_tokens=200)
        ci = [t for t in r.tool_calls if t.get("type") == "code_execution"]
        show(bool(ci), "code execution (tool)", f"{len(ci)} call(s); stdout={(ci[0].get('stdout') or '').strip()[:40] if ci else '-'}")
    except OtariError as e:
        show(False, "code execution (tool)", f"{e.status} {e.code} {e.detail[:200]}")


async def check_search(o: Otari) -> None:
    try:
        r = await o.chat(model=settings.hinter_model,
                         messages=say("Find the official Python docs page for the for statement. Reply with the URL."),
                         tools=[{"type": "otari_web_search", "max_uses": 1}], max_tokens=120)
        ws = [t for t in r.tool_calls if t.get("type") == "web_search"]
        srcs = [s.get("url") for t in ws for s in t.get("sources") or []]
        show(bool(ws), "web search", f"{len(ws)} search(es); sources={srcs[:2]}")
    except OtariError as e:
        show(False, "web search", f"{e.status} {e.code} {e.detail[:200]}")


async def check_guardrail(o: Otari) -> None:
    gr = [{"profile": p, "mode": "block"} for p in settings.guardrail_profiles] or None
    try:
        r = await o.chat(model=settings.hinter_model, user=PROBE_USER, guardrails=gr, max_tokens=20,
                         messages=say("My phone number is +1 415 555 0134 and I live at 12 Oak Street, call me"))
        show(False, "guardrail (block)", f"NOT blocked. Otari-Guardrails={json.dumps(r.guardrails)[:200]} "
             "-> mandate a PII guardrail in block mode (Organization -> Guardrails)")
    except OtariError as e:
        show(e.is_guardrail, "guardrail (block)", f"{e.status} {e.code}: {e.detail[:160]}")
    try:
        prof = await o.get_json("/tool-settings/guardrails/profiles")
        print(f"{DIM}      profiles: {[p.get('profile') for p in prof.get('profiles', [])]} available={prof.get('available')}{END}")
    except OtariError as e:
        print(f"{DIM}      profiles read failed: {e.status} {e.code}{END}")


async def check_mcp(o: Otari) -> None:
    if not settings.mcp_server_id:
        show(None, "mcp", "MOLLET_MCP_SERVER_ID not set (register <public-url>/classroom/mcp first)")
        return
    try:
        r = await o.chat(model=settings.hinter_model, mcp_server_ids=[settings.mcp_server_id], max_tokens=200,
                         messages=say('Call get_problem with problem_id "fizzbuzz" and tell me its title.'))
        calls = [t for t in r.tool_calls if t.get("type") == "mcp"]
        show(bool(calls), "mcp", f"{len(calls)} MCP call(s): {[(c.get('server'), c.get('name'), c.get('status')) for c in calls]} "
             f"answer={r.content[:80]!r}")
    except OtariError as e:
        show(False, "mcp", f"{e.status} {e.code} {e.detail[:200]}")


async def check_tools(o: Otari) -> None:
    try:
        print(f"{DIM}      GET /tools: {json.dumps(await o.get_json('/tools'))[:400]}{END}")
    except OtariError as e:
        print(f"{DIM}      GET /tools failed: {e.status} {e.code}{END}")


CHECKS = {"models": check_models, "users": check_end_users, "budget": check_key_budget,
          "code": check_code, "search": check_search, "guardrail": check_guardrail,
          "mcp": check_mcp, "tools": check_tools}


async def main(names: list[str]) -> None:
    if not settings.otari_api_key:
        sys.exit("Set OTARI_API_KEY in .env first.")
    print(f"Otari: {settings.otari_base_url}\n")
    o = Otari()
    t = time.perf_counter()
    for n in names or list(CHECKS):
        await CHECKS[n](o)
    await o.aclose()
    print(f"\n{DIM}done in {time.perf_counter() - t:.1f}s{END}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
