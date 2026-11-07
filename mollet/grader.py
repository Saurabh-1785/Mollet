"""Grading: the verdict comes from running code, not from a model's opinion.

1. Otari code execution (`POST /code/execute`) runs the student's function
   against the hidden tests in Otari's sandbox and returns real stdout.
2. The Grader (a separate open-weight coding model) reads those real results and
   writes feedback. It may run its own experiments with the built-in
   `otari_code_execution` tool. It never writes the corrected solution.

Checking work is billed to the class (no `user`), so a student with an empty
wallet can still submit.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .otari import ChatResult, Otari, OtariError
from .problems import Problem

HARNESS = r'''
import copy as _copy, json as _json, traceback as _tb
_MARK = {mark!r}
_SRC = {src!r}
_TESTS = _json.loads({tests!r})
_ENTRY = {entry!r}
_out = {{"load_error": None, "results": []}}
_ns = {{"__name__": "student"}}
try:
    exec(compile(_SRC, "student.py", "exec"), _ns)
except BaseException as _e:
    _line = _tb.extract_tb(_e.__traceback__)[-1].lineno if _e.__traceback__ else None
    if isinstance(_e, SyntaxError):
        _line = _e.lineno
    _out["load_error"] = {{"type": type(_e).__name__, "message": str(_e), "line": _line}}
_fn = _ns.get(_ENTRY)
if _out["load_error"] is None and not callable(_fn):
    _out["load_error"] = {{"type": "NameError", "message": "no function named " + _ENTRY + "()", "line": None}}
if _out["load_error"] is None:
    for _args, _expected in _TESTS:
        _r = {{"args": repr(tuple(_args))[1:-1].rstrip(","), "expected": repr(_expected)}}
        try:
            _got = _fn(*_copy.deepcopy(_args))
            _r["got"] = repr(_got)
            _same_kind = isinstance(_got, type(_expected)) and (isinstance(_got, bool) == isinstance(_expected, bool))
            _r["passed"] = bool(_got == _expected) and _same_kind
        except BaseException as _e:
            _r["got"] = None
            _r["passed"] = False
            _r["error"] = type(_e).__name__ + ": " + str(_e)
        _out["results"].append(_r)
print(_MARK + _json.dumps(_out))
'''


def build_harness(problem: Problem, code: str, mark: str) -> str:
    tests = json.dumps([[list(args), expected] for args, expected in problem.hidden_tests])
    return HARNESS.format(mark=mark, src=code, tests=tests, entry=problem.entry)


@dataclass
class TestRun:
    passed: bool
    passed_count: int
    total: int
    results: list[dict[str, Any]]
    load_error: dict[str, Any] | None
    stdout: str
    stderr: str
    request_id: str | None
    timed_out: bool = False


def parse_run(stdout: str, stderr: str, mark: str, total: int, request_id: str | None) -> TestRun:
    payload = None
    for line in stdout.splitlines():
        if line.startswith(mark):
            try:
                payload = json.loads(line[len(mark):])
            except ValueError:
                payload = None
    if payload is None:
        timed_out = "timeout" in stderr.lower() or "timed out" in stderr.lower()
        err = {"type": "Timeout" if timed_out else "RuntimeError",
               "message": "Your code did not finish (an infinite loop?)" if timed_out
               else (stderr.strip().splitlines() or ["The program stopped unexpectedly."])[-1][:300],
               "line": None}
        return TestRun(False, 0, total, [], err, stdout, stderr, request_id, timed_out)
    results = payload.get("results") or []
    n_pass = sum(1 for r in results if r.get("passed"))
    load_error = payload.get("load_error")
    # Student prints are useful to them; strip only our marker line.
    visible = "\n".join(l for l in stdout.splitlines() if not l.startswith(mark))
    return TestRun(
        passed=load_error is None and total > 0 and n_pass == total,
        passed_count=n_pass,
        total=total,
        results=results,
        load_error=load_error,
        stdout=visible,
        stderr=stderr,
        request_id=request_id,
    )


async def run_tests(otari: Otari, problem: Problem, code: str, *, user: str | None = None) -> TestRun:
    mark = f"__MOLLET_{secrets.token_hex(8)}__"
    res = await otari.execute_code(build_harness(problem, code, mark), user=user,
                                   timeout_s=settings.code_timeout_s)
    return parse_run(res.stdout, res.stderr, mark, len(problem.hidden_tests), res.request_id)


GRADER_SYSTEM = """You are the Grader in Mollet, a coding tutor for beginners.
You receive a student's Python function and the REAL results of running it against tests
in a sandbox. Write short, kind feedback that helps the student find the bug themselves.

Rules:
- Never write the corrected function or any line of fixed code. Describe, don't solve.
- Point at the first failing case and what it reveals. One or two sentences, max 60 words.
- If every test passed, congratulate briefly and name one thing they did well.
- You may use the code execution tool to test a hypothesis about the bug; never to write the fix.
- Also give a "mistake" tag: 3-8 words naming the misconception (e.g. "used = instead of ==",
  "forgot upper-case letters", "returned inside the loop"). Empty string if all tests passed.

Reply with ONLY a JSON object: {"feedback": "...", "mistake": "..."}"""


@dataclass
class Grade:
    run: TestRun
    feedback: str
    mistake: str
    grader: dict[str, Any] | None = None
    grader_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_grader_json(text: str) -> tuple[str, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            return str(obj.get("feedback", "")).strip(), str(obj.get("mistake", "")).strip()[:80]
        except ValueError:
            pass
    return text.strip()[:400], ""


def fallback_feedback(run: TestRun) -> tuple[str, str]:
    if run.load_error:
        e = run.load_error
        where = f" on line {e['line']}" if e.get("line") else ""
        return f"Python stopped before any test ran: {e['type']}{where}. Read that line closely.", e["type"]
    if run.passed:
        return "Every test passed. Nice work!", ""
    first = next((r for r in run.results if not r.get("passed")), None)
    if first:
        got = first.get("error") or first.get("got")
        return (f"Check the case {first['args']}: expected {first['expected']}, got {got}.", "")
    return "Some tests failed.", ""


async def grade(otari: Otari, problem: Problem, code: str, student_id: str) -> Grade:
    run = await run_tests(otari, problem, code)  # billed to the class pool
    summary = {
        "load_error": run.load_error,
        "passed": f"{run.passed_count}/{run.total}",
        "results": run.results,
        "stdout_tail": run.stdout[-500:],
    }
    messages = [
        {"role": "system", "content": GRADER_SYSTEM},
        {"role": "user", "content": (
            f"Problem: {problem.statement}\nFunction name: {problem.entry}\n\n"
            f"Student code:\n```python\n{code}\n```\n\nSandbox results (real):\n"
            f"```json\n{json.dumps(summary, indent=1)[:4000]}\n```"
        )},
    ]
    tools = [{"type": "otari_code_execution"}] if settings.grader_uses_code_tool and not run.passed else None
    async def ask(with_tools: list[dict[str, Any]] | None) -> ChatResult:
        return await otari.chat(
            model=settings.grader_model,
            messages=messages,
            tools=with_tools,
            metadata={"app": "mollet", "role": "grader", "student": student_id, "problem": problem.id},
            max_tokens=400,
            temperature=0.2,
            max_tool_iterations=3 if with_tools else None,
        )

    try:
        try:
            res = await ask(tools)
        except OtariError as e:
            if not tools or e.is_policy_refusal:
                raise
            res = await ask(None)  # code tool unavailable: grade from the sandbox results alone
        feedback, mistake = _parse_grader_json(res.content)
        if not feedback:
            feedback, mistake = fallback_feedback(run)
        if run.passed:
            mistake = ""
        return Grade(run, feedback, mistake, grader=res.debug())
    except OtariError as e:
        feedback, mistake = fallback_feedback(run)
        return Grade(run, feedback, mistake, grader_error=f"{e.code or e.status}: {e.detail}")
