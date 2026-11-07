"""SQLite storage: students, attempts, hints and refusals."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id   TEXT PRIMARY KEY,           -- sent to Otari as the `user` (end user id)
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   TEXT NOT NULL REFERENCES students(id),
    problem_id   TEXT NOT NULL,
    code         TEXT NOT NULL,
    passed       INTEGER NOT NULL,
    passed_count INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    mistake      TEXT,                -- short tag the Grader writes, read by MCP
    feedback     TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL REFERENCES students(id),
    problem_id      TEXT NOT NULL,
    level           INTEGER NOT NULL,
    question        TEXT,
    text            TEXT NOT NULL,
    model_requested TEXT,
    model_served    TEXT,
    provider        TEXT,
    fallback        INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    request_id      TEXT,
    meta            TEXT,             -- JSON: sources, tool calls
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refusals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    kind       TEXT NOT NULL,         -- budget_exceeded | guardrail_violation | app_rule | ...
    scope      TEXT,
    detail     TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hints_student ON hints(student_id, problem_id);
CREATE INDEX IF NOT EXISTS attempts_student ON attempts(student_id, problem_id);
"""

SEED_STUDENTS = [("student_001", "Asha"), ("student_002", "Ben"), ("student_003", "Chen")]

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect(path or settings.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init(path: Path | None = None) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)
        c.executemany("INSERT OR IGNORE INTO students(id, name) VALUES (?, ?)", SEED_STUDENTS)


# --- students -------------------------------------------------------------------


def students() -> list[dict[str, Any]]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT id, name FROM students ORDER BY id")]


def student(student_id: str) -> dict[str, Any] | None:
    with connect() as c:
        row = c.execute("SELECT id, name FROM students WHERE id = ?", (student_id,)).fetchone()
        return dict(row) if row else None


# --- hints ----------------------------------------------------------------------


def add_hint(**row: Any) -> int:
    row.setdefault("created_at", now())
    if isinstance(row.get("meta"), (dict, list)):
        row["meta"] = json.dumps(row["meta"])
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with connect() as c:
        cur = c.execute(f"INSERT INTO hints ({cols}) VALUES ({marks})", tuple(row.values()))
        return int(cur.lastrowid)


def hints_for(student_id: str, problem_id: str) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM hints WHERE student_id = ? AND problem_id = ? ORDER BY id",
            (student_id, problem_id),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
        out.append(d)
    return out


def hint_level_reached(student_id: str, problem_id: str) -> int:
    with connect() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(level), 0) FROM hints WHERE student_id = ? AND problem_id = ?",
            (student_id, problem_id),
        ).fetchone()
        return int(row[0])


def average_cost_by_level() -> dict[int, float]:
    with connect() as c:
        rows = c.execute(
            "SELECT level, AVG(cost_usd) FROM hints WHERE cost_usd > 0 GROUP BY level"
        ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows}


# --- attempts -------------------------------------------------------------------


def add_attempt(**row: Any) -> int:
    row.setdefault("created_at", now())
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with connect() as c:
        cur = c.execute(f"INSERT INTO attempts ({cols}) VALUES ({marks})", tuple(row.values()))
        return int(cur.lastrowid)


def attempts_for(student_id: str, problem_id: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM attempts WHERE student_id = ?"
    args: tuple[Any, ...] = (student_id,)
    if problem_id:
        q += " AND problem_id = ?"
        args += (problem_id,)
    with connect() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id", args)]


def solved_problems(student_id: str) -> set[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT DISTINCT problem_id FROM attempts WHERE student_id = ? AND passed = 1",
            (student_id,),
        ).fetchall()
    return {r[0] for r in rows}


def history(student_id: str, limit: int = 8) -> dict[str, Any]:
    """What the MCP tool `get_student_history` returns: recent mistakes and hint use."""
    with connect() as c:
        mistakes = c.execute(
            "SELECT problem_id, mistake, passed_count, total, created_at FROM attempts "
            "WHERE student_id = ? AND passed = 0 AND mistake IS NOT NULL AND mistake != '' "
            "ORDER BY id DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
        hint_rows = c.execute(
            "SELECT problem_id, MAX(level) AS top_level, COUNT(*) AS n FROM hints "
            "WHERE student_id = ? GROUP BY problem_id",
            (student_id,),
        ).fetchall()
    return {
        "student_id": student_id,
        "recent_mistakes": [dict(r) for r in mistakes],
        "hint_use": [dict(r) for r in hint_rows],
        "solved": sorted(solved_problems(student_id)),
    }


# --- refusals -------------------------------------------------------------------


def add_refusal(student_id: str, kind: str, scope: str | None, detail: str) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO refusals (student_id, kind, scope, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (student_id, kind, scope, detail[:500], now()),
        )


def refusals(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as c:
        return [
            dict(r)
            for r in c.execute("SELECT * FROM refusals ORDER BY id DESC LIMIT ?", (limit,))
        ]


# --- independence score ---------------------------------------------------------

MAX_LADDER = 15  # 1+2+3+4+5: every rung of the ladder used


def independence(student_id: str) -> dict[str, Any]:
    """Average, over solved problems, of 1 - (sum of hint levels used before the
    first pass / 15). Solving with no hints scores 100; using every rung scores 0."""
    with connect() as c:
        firsts = c.execute(
            "SELECT problem_id, MIN(id) AS first_pass_id, MIN(created_at) AS at FROM attempts "
            "WHERE student_id = ? AND passed = 1 GROUP BY problem_id",
            (student_id,),
        ).fetchall()
        per_problem = []
        for f in firsts:
            row = c.execute(
                "SELECT COALESCE(SUM(DISTINCT level), 0), COUNT(*) FROM hints "
                "WHERE student_id = ? AND problem_id = ? AND created_at <= ?",
                (student_id, f["problem_id"], f["at"]),
            ).fetchone()
            used = int(row[0])
            per_problem.append(
                {
                    "problem_id": f["problem_id"],
                    "hint_points": used,
                    "hints": int(row[1]),
                    "score": round(100 * max(0.0, 1 - used / MAX_LADDER)),
                }
            )
    score = round(sum(p["score"] for p in per_problem) / len(per_problem)) if per_problem else None
    return {"score": score, "solved": len(per_problem), "problems": per_problem}
