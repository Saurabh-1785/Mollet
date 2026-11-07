"""The hint ladder: five rungs, cheapest first. Mollet never gives the answer.

Which Otari features each rung uses:
  1 Point        Hinter policy + built-in web search (max_uses: 1) -> a real docs link
  2 Explain      Hinter policy + classroom MCP server (past mistakes)
  3 Approach     Hinter policy + MCP
  4 Sketch       Mentor policy (stronger model, tiers down near the budget cap) + MCP
  5 Walk-through Mentor policy + MCP

Every rung is billed to the student's own wallet (`user` = student id) and passes
the guardrails in block mode.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from . import db
from .config import settings
from .grader import run_tests
from .otari import ChatResult, Otari, OtariError, summarise_tool_call
from .problems import Problem


@dataclass(frozen=True)
class Rung:
    level: int
    name: str
    tagline: str
    rule: str
    tier: str  # "hinter" | "mentor"
    est_usd: float  # shown until real costs exist for the rung
    words: int


LADDER: list[Rung] = [
    Rung(1, "Point", "Name the idea + one docs link",
         "Name the ONE Python concept the student needs, in one sentence, and give exactly one "
         "link to the official documentation page for it (docs.python.org preferred). Use the web "
         "search tool once to find that page. No code. No explanation beyond one sentence.",
         "hinter", 0.0006, 50),
    Rung(2, "Explain", "Explain the missing concept",
         "Explain the concept the student is missing in plain words. You may show a tiny example "
         "of the concept on a DIFFERENT task (different names, different data). Never code for "
         "this problem.",
         "hinter", 0.0010, 110),
    Rung(3, "Approach", "Plan the steps, no code",
         "Help the student plan: give 3-5 numbered steps in plain English describing an approach. "
         "Absolutely no code, no pseudocode, no function definitions.",
         "hinter", 0.0015, 130),
    Rung(4, "Sketch", "Pseudocode with blanks",
         "Give pseudocode or a partial skeleton with blanks written as ___ that the student must "
         "fill in. The skeleton must NOT run or pass as-is. Leave the key logic as a blank.",
         "mentor", 0.0040, 150),
    Rung(5, "Walk-through", "Walk through the hardest part",
         "Walk through ONLY the hardest part of the problem, step by step, using a concrete input. "
         "You may show at most 3 lines of code for that part, never the whole function.",
         "mentor", 0.0080, 200),
]
BY_LEVEL = {r.level: r for r in LADDER}
MAX_LEVEL = len(LADDER)


def model_for(rung: Rung) -> str:
    return settings.hinter_model if rung.tier == "hinter" else settings.mentor_model


def price_preview() -> dict[int, dict[str, Any]]:
    """Each rung's price is its real token cost: the average of what Otari billed
    for that rung so far (usage.cost_usd), or a starting estimate."""
    seen = db.average_cost_by_level()
    return {
        r.level: {"usd": round(seen.get(r.level, r.est_usd), 6), "measured": r.level in seen}
        for r in LADDER
    }


# --- app rules (not Otari features): PII pre-check and "no full solutions" -----------

_PII_PATTERNS = {
    "phone number": re.compile(r"(?:\+?\d[\s().-]?){8,}\d"),
    "email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
}


def app_pii_check(text: str) -> str | None:
    for label, pat in _PII_PATTERNS.items():
        if pat.search(text or ""):
            return label
    return None


_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.S)


def _code_blocks(text: str) -> list[str]:
    return [b.strip("\n") for b in _FENCE.findall(text)]


def heuristic_leak(text: str, problem: Problem, level: int) -> str | None:
    """Cheap structural check. Returns a reason when the hint gives too much away."""
    blocks = _code_blocks(text)
    code = "\n".join(blocks)
    defines_entry = re.search(rf"\bdef\s+{re.escape(problem.entry)}\s*\(", text) is not None
    lines = [l for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    if level <= 3 and defines_entry:
        return "defines the solution function"
    if level == 1 and blocks:
        return "rung 1 allows no code"
    if level == 3 and len(lines) > 1:
        return "rung 3 allows no code"
    if level == 4 and defines_entry and "___" not in code:
        return "skeleton has no blanks"
    if level == 5 and defines_entry and len(lines) > 4:
        return "shows the whole function"
    return None


async def runs_as_solution(otari: Otari, text: str, problem: Problem) -> bool:
    """The strong check: if the hint's own code passes the hidden tests in Otari's
    sandbox, it IS the answer. Only runs when the hint defines the function."""
    if not re.search(rf"\bdef\s+{re.escape(problem.entry)}\s*\(", text):
        return False
    code = "\n\n".join(_code_blocks(text)) or text
    try:
        run = await run_tests(otari, problem, code)
    except OtariError:
        return False
    return run.passed


def strip_code(text: str) -> str:
    return _FENCE.sub("_[code removed by Mollet: it gave away too much]_", text).strip()


# --- prompt -------------------------------------------------------------------------

SYSTEM = """You are Mollet, a patient programming mentor for beginner Python students.
Your one unbreakable rule: you NEVER give the full solution or complete working code for the
student's problem. You give the smallest useful hint for the rung of the hint ladder you are
asked for, then stop. Students pay for every hint from a small weekly wallet, so be brief.

Rung {level} of 5 ({name}): {rule}
Keep it under {words} words. Address the student as "you". Use Markdown sparingly."""


def build_messages(
    *,
    student_id: str,
    problem: Problem,
    rung: Rung,
    question: str,
    code: str,
    previous: list[dict[str, Any]],
    use_mcp: bool,
) -> list[dict[str, Any]]:
    system = SYSTEM.format(level=rung.level, name=rung.name, rule=rung.rule, words=rung.words)
    if rung.level >= 2:
        if use_mcp:
            system += (
                "\n\nBefore answering, call the classroom tools: get_student_history(student_id="
                f"\"{student_id}\") and get_problem(problem_id=\"{problem.id}\"). If the history shows a "
                "past mistake that is relevant here, mention it in one short sentence "
                "(e.g. \"Last time you mixed up = and ==\"). Never reveal hidden tests."
            )
        else:
            hist = db.history(student_id, limit=5)
            system += (
                "\n\nThe student's recent mistakes (from the classroom record): "
                f"{json.dumps(hist['recent_mistakes'])}. If one is relevant, mention it in one "
                "short sentence."
            )
    prior = "\n".join(f"- Rung {h['level']} ({BY_LEVEL[h['level']].name}): {h['text'][:400]}"
                      for h in previous) or "(none)"
    user = (
        f"Problem ({problem.title}): {problem.statement}\nExample: {problem.example}\n"
        f"Concept being practised: {problem.concept}\n\n"
        f"Hints the student already bought:\n{prior}\n\n"
        f"Student's current code:\n```python\n{code.strip() or '(empty)'}\n```\n\n"
        f"Student's question: {question.strip() or '(no question, they are stuck)'}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@dataclass
class HintOutcome:
    level: int
    text: str
    cost_usd: float
    sources: list[dict[str, Any]]
    debug: dict[str, Any]
    redacted: bool
    hint_id: int


async def request_hint(
    otari: Otari, *, student_id: str, problem: Problem, level: int, question: str, code: str
) -> HintOutcome:
    rung = BY_LEVEL[level]
    previous = db.hints_for(student_id, problem.id)
    use_mcp = bool(settings.mcp_server_id) and level >= 2
    messages = build_messages(student_id=student_id, problem=problem, rung=rung,
                              question=question, code=code, previous=previous, use_mcp=use_mcp)
    tools = None
    if level == 1 and settings.web_search_enabled:
        tools = [{"type": "otari_web_search", "max_uses": 1}]
    guardrails = [{"profile": p, "mode": "block"} for p in settings.guardrail_profiles] or None
    common = dict(
        model=model_for(rung),
        user=student_id,  # -> billed to this student's end-user budget (their wallet)
        tools=tools,
        mcp_server_ids=[settings.mcp_server_id] if use_mcp else None,
        guardrails=guardrails,
        metadata={"app": "mollet", "role": "hint", "rung": str(level), "problem": problem.id},
        max_tokens=600,
        max_tool_iterations=4 if (tools or use_mcp) else None,
    )

    tool_note = None
    try:
        res: ChatResult = await otari.chat(messages=messages, **common)
    except OtariError as e:
        if e.is_policy_refusal or e.status in (401, 429) or not (tools or use_mcp):
            raise
        # A workspace tool (search / MCP) is off or failed: still give the hint, without it.
        tool_note = f"tools skipped ({e.code or e.status})"
        common.update(tools=None, mcp_server_ids=None, max_tool_iterations=None)
        if use_mcp:
            messages = build_messages(student_id=student_id, problem=problem, rung=rung, question=question,
                                      code=code, previous=previous, use_mcp=False)
        res = await otari.chat(messages=messages, **common)
    total_cost = res.cost_usd
    all_calls = list(res.tool_calls)
    text = res.content
    redacted = False

    # App rule: never the full answer. Structural check first, then the sandbox check.
    reason = heuristic_leak(text, problem, level)
    if not reason and await runs_as_solution(otari, text, problem):
        reason = "the hint's code passes the hidden tests"
    if reason:
        retry_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                f"That draft gives too much away ({reason}). Rewrite it following rung {level}'s "
                "rule exactly. Do not include a working solution."
            )},
        ]
        common["tools"] = None
        common["mcp_server_ids"] = None
        common["max_tool_iterations"] = None
        try:
            res2 = await otari.chat(messages=retry_msgs, **common)
        except OtariError:
            # e.g. the wallet ran out on the rewrite: show the first draft minus its code.
            text, redacted = strip_code(text), True
        else:
            total_cost += res2.cost_usd
            all_calls += res2.tool_calls
            text = res2.content
            if heuristic_leak(text, problem, level) or await runs_as_solution(otari, text, problem):
                text = strip_code(text)
                redacted = True
            res = ChatResult(**{**res.__dict__, "content": text, "model_served": res2.model_served,
                                "provider": res2.provider, "fallback": res.fallback or res2.fallback})

    sources = []
    for call in all_calls:
        if call.get("type") == "web_search":
            for s in call.get("sources") or []:
                if s.get("url"):
                    sources.append({"url": s["url"], "title": s.get("title") or s["url"]})
    debug = res.debug()
    debug["cost_usd"] = round(total_cost, 6)
    debug["tool_calls"] = [summarise_tool_call(c) for c in all_calls]
    debug["mcp"] = "on" if use_mcp else ("off (history inlined)" if level >= 2 else "n/a")
    debug["leak_check"] = reason or "clean"
    if tool_note:
        debug["mcp"] = f"{debug['mcp']} · {tool_note}"

    hint_id = db.add_hint(
        student_id=student_id,
        problem_id=problem.id,
        level=level,
        question=question[:1000],
        text=text,
        model_requested=res.model_requested,
        model_served=res.model_served,
        provider=res.provider,
        fallback=int(res.fallback),
        cost_usd=total_cost,
        request_id=res.request_id,
        meta={"sources": sources[:3], "debug": debug},
    )
    return HintOutcome(level, text, total_cost, sources[:3], debug, redacted, hint_id)
