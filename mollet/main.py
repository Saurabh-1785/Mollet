"""Mollet web app: FastAPI + server-rendered pages. The Otari key never reaches the browser."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import db, hints, problems, wallet
from .config import settings
from .grader import grade
from .mcp_server import asgi_app as mcp_asgi_app
from .mcp_server import running as mcp_running
from .otari import Otari, OtariError

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=HERE / "templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    app.state.otari = Otari()
    async with mcp_running():
        yield
    await app.state.otari.aclose()


app = FastAPI(title="Mollet", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.mount("/classroom", mcp_asgi_app())  # MCP endpoint: /classroom/mcp


def otari(request: Request) -> Otari:
    return request.app.state.otari


def page(request: Request, name: str, **ctx: Any):
    ctx.update(request=request, settings=settings, students=db.students(), active=name.split(".")[0])
    return templates.TemplateResponse(request, name, ctx)


# --- refusal copy: what the student sees for each Otari error code ---------------


def refusal(e: OtariError, student_id: str) -> dict[str, Any]:
    if e.is_budget and (e.scope in (None, "user")):
        kind, title = "wallet_empty", "Wallet empty"
        msg = ("You've spent this week's hint wallet. Try what you've learned so far, or run "
               "the tests: checking your code is always free.")
    elif e.is_budget:
        kind, title = "class_budget", "Class budget reached"
        msg = ("Your class has used its AI budget for this week, so hints are paused for "
               "everyone. Your teacher can raise the cap.")
    elif e.is_guardrail:
        kind, title = "guardrail", "Message blocked to keep you safe"
        msg = ("It looks like your message included personal information, like a phone number "
               "or address. Mollet never needs it. Remove it and ask again.")
    elif e.code == "user_blocked":
        kind, title, msg = "blocked", "Hints paused", "Your teacher has paused hints for your account."
    elif e.code == "insufficient_funds" or e.status == 402:
        kind, title = "setup", "Otari account out of credit"
        msg = "The Otari organization has no credit left, so no model can answer. Add credit in Otari's Billing page."
    elif e.status == 401:
        kind, title = "setup", "Mollet isn't connected to Otari"
        msg = "The Otari key is missing or invalid. Set OTARI_API_KEY to a service key and restart."
    elif e.code in ("gateway_unreachable", "gateway_timeout"):
        kind, title = "error", "Couldn't reach Otari"
        msg = "The gateway didn't answer. Check the connection and try again in a moment."
    elif e.code in ("provider_not_configured", "invalid_model", "model_not_found", "model_not_allowed"):
        kind, title = "setup", "Mollet isn't set up yet"
        msg = f"The gateway refused the model ({e.code}). Check the model names on the Otari status page."
    else:
        kind, title = "error", "Couldn't reach the AI"
        msg = "Something went wrong talking to the gateway. Try again in a moment."
    db.add_refusal(student_id, e.code or str(e.status), e.scope, e.detail)
    return {
        "kind": kind, "title": title, "message": msg,
        "otari": {"status": e.status, "code": e.code, "scope": e.scope,
                  "retry_after": e.retry_after, "request_id": e.request_id, "detail": e.detail},
    }


def _need_student(student_id: str) -> dict[str, Any]:
    s = db.student(student_id)
    if not s:
        raise HTTPException(404, "Unknown student")
    return s


def _need_problem(problem_id: str) -> problems.Problem:
    p = problems.get(problem_id)
    if not p:
        raise HTTPException(404, "Unknown problem")
    return p


# --- pages ------------------------------------------------------------------------


@app.get("/")
async def home() -> RedirectResponse:
    return RedirectResponse(f"/learn/{db.SEED_STUDENTS[0][0]}/{problems.PROBLEMS[0].id}")


@app.get("/learn/{student_id}")
async def learn_default(student_id: str) -> RedirectResponse:
    _need_student(student_id)
    return RedirectResponse(f"/learn/{student_id}/{problems.PROBLEMS[0].id}")


@app.get("/learn/{student_id}/{problem_id}")
async def learn(request: Request, student_id: str, problem_id: str):
    s = _need_student(student_id)
    p = _need_problem(problem_id)
    solved = db.solved_problems(student_id)
    attempts = db.attempts_for(student_id, problem_id)
    state = {
        "student": s,
        "problem": problems.public_view(p),
        "starter": attempts[-1]["code"] if attempts else p.starter,
        "hints": [_hint_view(h) for h in db.hints_for(student_id, problem_id)],
        "ladder": [{"level": r.level, "name": r.name, "tagline": r.tagline, "tier": r.tier,
                    "model": hints.model_for(r)} for r in hints.LADDER],
        "prices": hints.price_preview(),
        "solved": problem_id in solved,
        "attempts": len(attempts),
        "independence": db.independence(student_id),
    }
    return page(request, "learn.html", student=s, problem=p, problems=problems.PROBLEMS,
                solved=solved, state=state)


@app.get("/teacher")
async def teacher(request: Request):
    return page(request, "teacher.html")


@app.get("/status")
async def status(request: Request):
    return page(request, "status.html")


# --- JSON API -------------------------------------------------------------------------


class HintIn(BaseModel):
    student_id: str
    problem_id: str
    question: str = Field("", max_length=2000)
    code: str = Field("", max_length=20000)


class SubmitIn(BaseModel):
    student_id: str
    problem_id: str
    code: str = Field(..., max_length=20000)


def _hint_view(h: dict[str, Any]) -> dict[str, Any]:
    meta = h.get("meta") or {}
    return {"id": h["id"], "level": h["level"], "name": hints.BY_LEVEL[h["level"]].name,
            "text": h["text"], "cost_usd": h["cost_usd"], "sources": meta.get("sources", []),
            "debug": meta.get("debug", {}), "question": h.get("question") or "",
            "created_at": h["created_at"]}


@app.post("/api/hint")
async def api_hint(body: HintIn, request: Request):
    _need_student(body.student_id)
    p = _need_problem(body.problem_id)
    level = db.hint_level_reached(body.student_id, p.id) + 1
    if level > hints.MAX_LEVEL:
        return JSONResponse({"error": {"kind": "ladder_top", "title": "Top of the ladder",
                                       "message": "You've used every rung for this problem. "
                                                  "Try a fix and run the tests."}}, 409)
    if settings.app_pii_precheck:
        found = hints.app_pii_check(body.question)
        if found:
            db.add_refusal(body.student_id, "app_rule_pii", None, found)
            return JSONResponse({"error": {"kind": "guardrail", "title": "Message blocked to keep you safe",
                                           "message": f"Your message looks like it has a {found}. "
                                                      "Remove it and ask again.",
                                           "app_rule": True}}, 403)
    o = otari(request)
    try:
        out = await hints.request_hint(o, student_id=body.student_id, problem=p, level=level,
                                       question=body.question, code=body.code)
    except OtariError as e:
        w = await wallet.wallet(o, body.student_id)
        return JSONResponse({"error": refusal(e, body.student_id), "wallet": w}, e.status)
    w = await wallet.wallet(o, body.student_id)
    hint = _hint_view({"id": out.hint_id, "level": out.level, "text": out.text,
                       "cost_usd": out.cost_usd, "meta": {"sources": out.sources, "debug": out.debug},
                       "question": body.question, "created_at": db.now()})
    hint["redacted"] = out.redacted
    return {"hint": hint, "wallet": w, "prices": hints.price_preview()}


@app.post("/api/submit")
async def api_submit(body: SubmitIn, request: Request):
    _need_student(body.student_id)
    p = _need_problem(body.problem_id)
    o = otari(request)
    try:
        g = await grade(o, p, body.code, body.student_id)
    except OtariError as e:
        return JSONResponse({"error": refusal(e, body.student_id)}, e.status)
    run = g.run
    db.add_attempt(student_id=body.student_id, problem_id=p.id, code=body.code,
                   passed=int(run.passed), passed_count=run.passed_count, total=run.total,
                   mistake=g.mistake or None, feedback=g.feedback)
    return {
        "passed": run.passed, "passed_count": run.passed_count, "total": run.total,
        "results": run.results, "load_error": run.load_error, "stdout": run.stdout[-2000:],
        "feedback": g.feedback, "mistake": g.mistake,
        "sandbox_request_id": run.request_id, "grader": g.grader, "grader_error": g.grader_error,
        "independence": db.independence(body.student_id),
    }


@app.get("/api/wallet/{student_id}")
async def api_wallet(student_id: str, request: Request):
    _need_student(student_id)
    return await wallet.wallet(otari(request), student_id)


@app.get("/api/class")
async def api_class(request: Request):
    o = otari(request)
    studs = db.students()
    wallets = await asyncio.gather(*(wallet.wallet(o, s["id"]) for s in studs))
    rows = []
    for s, w in zip(studs, wallets):
        with db.connect() as c:
            hint_n, hint_cost = c.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM hints WHERE student_id = ?",
                (s["id"],)).fetchone()
            by_level = dict(c.execute(
                "SELECT level, COUNT(*) FROM hints WHERE student_id = ? GROUP BY level",
                (s["id"],)).fetchall())
        ind = db.independence(s["id"])
        rows.append({**s, "wallet": w, "hints": hint_n, "hint_cost_usd": round(hint_cost, 6),
                     "by_level": by_level, "solved": ind["solved"], "independence": ind["score"],
                     "problems": ind["problems"]})
    with db.connect() as c:
        models = [dict(r) for r in c.execute(
            "SELECT model_requested, model_served, COUNT(*) AS n, SUM(fallback) AS fallbacks, "
            "SUM(cost_usd) AS cost FROM hints GROUP BY model_requested, model_served ORDER BY n DESC")]
    return {"class_budget": await wallet.class_budget(o), "students": rows,
            "refusals": db.refusals(15), "models": models, "total_problems": len(problems.PROBLEMS)}


@app.get("/api/status")
async def api_status(request: Request):
    """Live checks behind the 'Otari features' page."""
    o = otari(request)

    async def probe(path: str) -> dict[str, Any]:
        try:
            return {"ok": True, "data": await o.get_json(path)}
        except OtariError as e:
            return {"ok": False, "error": f"{e.code or e.status}: {e.detail[:160]}"}
        except Exception as e:  # network errors etc.
            return {"ok": False, "error": type(e).__name__}

    tools, profiles, budgets, keyb = await asyncio.gather(
        probe("/tools"), probe("/tool-settings/guardrails/profiles"),
        probe("/end-user-budgets"), probe("/key/budget"))
    with db.connect() as c:
        last = {r["k"]: r["v"] for r in c.execute(
            "SELECT 'fallbacks' AS k, COUNT(*) AS v FROM hints WHERE fallback = 1 UNION ALL "
            "SELECT 'hints', COUNT(*) FROM hints UNION ALL "
            "SELECT 'graded', COUNT(*) FROM attempts UNION ALL "
            "SELECT 'guardrail_blocks', COUNT(*) FROM refusals WHERE kind = 'guardrail_violation' UNION ALL "
            "SELECT 'budget_blocks', COUNT(*) FROM refusals WHERE kind = 'budget_exceeded'")}
        served = [dict(r) for r in c.execute(
            "SELECT DISTINCT model_served FROM hints WHERE model_served IS NOT NULL LIMIT 10")]
        mcp_used = c.execute("SELECT COUNT(*) FROM hints WHERE meta LIKE '%\"type\": \"mcp\"%'").fetchone()[0]
        search_used = c.execute(
            "SELECT COUNT(*) FROM hints WHERE meta LIKE '%\"type\": \"web_search\"%'").fetchone()[0]
    return {
        "configured": settings.configured, "mock": settings.mock, "base_url": settings.otari_base_url,
        "models": {"hinter": settings.hinter_model, "mentor": settings.mentor_model,
                   "grader": settings.grader_model,
                   "served": [s["model_served"] for s in served]},
        "mcp_server_id": settings.mcp_server_id or None,
        "guardrail_profiles": settings.guardrail_profiles,
        "app_pii_precheck": settings.app_pii_precheck,
        "probes": {"tools": tools, "guardrail_profiles": profiles,
                   "end_user_budgets": budgets, "key_budget": keyb},
        "counters": {**last, "mcp_calls": mcp_used, "search_hints": search_used},
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True}
