"""Wallets are Otari end-user budgets; the class cap is the key's/workspace's ceiling.

Mollet keeps no balance of its own: the numbers on screen are read back from
Otari, which is also what refuses a hint when a wallet is empty.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings
from .otari import Otari, OtariError

_budget_cache: tuple[float, list[dict[str, Any]]] | None = None


async def _budgets(otari: Otari) -> list[dict[str, Any]]:
    global _budget_cache
    if _budget_cache and time.monotonic() - _budget_cache[0] < 60:
        return _budget_cache[1]
    try:
        data = await otari.end_user_budgets()
    except OtariError:
        data = []
    _budget_cache = (time.monotonic(), data)
    return data


def clear_cache() -> None:
    global _budget_cache
    _budget_cache = None


def next_monday_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    days = (7 - now.weekday()) % 7 or 7
    return (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def refill_label(iso: str | None) -> str:
    """'Monday' style label for when the wallet refills."""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00")) if iso else next_monday_utc()
    except ValueError:
        when = next_monday_utc()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = when - datetime.now(timezone.utc)
    if delta.total_seconds() < 0:
        return "soon"
    if delta < timedelta(days=1):
        hours = max(1, int(delta.total_seconds() // 3600))
        return f"in {hours}h"
    return when.strftime("%A")  # e.g. "Monday"


async def wallet(otari: Otari, student_id: str) -> dict[str, Any]:
    budgets = await _budgets(otari)
    default = next((b for b in budgets if b.get("is_default")), budgets[0] if budgets else None)
    source = "otari"
    try:
        eu = await otari.end_user(student_id)
    except OtariError as e:
        eu, source = None, f"unavailable ({e.code or e.status})"
    budget = default
    if eu and eu.get("budget_id"):
        budget = next((b for b in budgets if b.get("budget_id") == eu["budget_id"]), default)
    limit = budget.get("max_budget") if budget else None
    if limit is None:
        limit, limit_source = settings.fallback_wallet_usd, "app default"
    else:
        limit_source = budget.get("name") or "end-user budget"
    spend = float((eu or {}).get("spend") or 0)
    reserved = float((eu or {}).get("reserved") or 0)
    remaining = max(0.0, float(limit) - spend)
    return {
        "student_id": student_id,
        "spend_usd": round(spend, 6),
        "reserved_usd": round(reserved, 6),
        "limit_usd": float(limit),
        "remaining_usd": round(remaining, 6),
        "pct_used": min(100.0, 100 * spend / float(limit)) if limit else 100.0,
        "requests": (eu or {}).get("current_requests", 0),
        "blocked": bool((eu or {}).get("blocked")),
        "refills": refill_label((eu or {}).get("next_budget_reset_at")),
        "budget_name": limit_source,
        "source": source,
        "exists_in_otari": eu is not None,
    }


async def class_budget(otari: Otari) -> dict[str, Any]:
    """The teacher's cap: the tightest workspace / key ceiling from GET /key/budget."""
    try:
        data = await otari.key_budget()
    except OtariError as e:
        return {"available": False, "reason": f"{e.code or e.status}: {e.detail[:120]}"}
    limits = data.get("limits") or []
    ceilings = [l for l in limits if l.get("scope") != "user"]
    tightest = None
    for l in ceilings:
        rem = l.get("remaining_usd")
        if rem is not None and (tightest is None or rem < tightest.get("remaining_usd", 1e9)):
            tightest = l
    out: dict[str, Any] = {
        "available": True,
        "enforced": data.get("budgets_enforced", True),
        "remaining_usd": data.get("remaining_usd"),
        "limits": ceilings,
    }
    if tightest:
        lim = tightest.get("limit_usd") or settings.class_budget_usd
        rem = float(tightest.get("remaining_usd") or 0)
        used = tightest.get("used_usd")
        used = float(used) if used is not None else max(0.0, lim - rem)
        out.update(
            scope=tightest.get("scope"),
            limit_usd=lim,
            limit_is_display=tightest.get("limit_usd") is None,
            used_usd=round(used, 6),
            pct_used=min(100.0, 100 * used / lim) if lim else 100.0,
            resets=refill_label(tightest.get("resets_at")),
        )
    return out
