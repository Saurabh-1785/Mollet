"""Thin client for the Otari gateway (https://api.otari.ai/api/v1).

Plain httpx rather than the OpenAI SDK, because Mollet needs what the SDK hides:
the routing headers (`Otari-Model`, `Otari-Fallback`, ...), the inline cost
(`usage.cost_usd`), gateway tool calls (`otari_tool_calls`) and Otari's own
request fields (`mcp_server_ids`, `guardrails`).

Every call is made with ONE service key that never leaves this server. Requests
made on a student's behalf set `user` to the student id, so Otari bills that
student's end-user budget (their wallet).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings


class OtariError(Exception):
    """A refusal or failure from the gateway, keyed by its stable error code."""

    def __init__(
        self,
        status: int,
        code: str | None,
        detail: str,
        *,
        scope: str | None = None,
        retry_after: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"{status} {code or ''} {detail}".strip())
        self.status = status
        self.code = code
        self.detail = detail
        self.scope = scope
        self.retry_after = retry_after
        self.request_id = request_id

    @property
    def is_budget(self) -> bool:
        return self.code == "budget_exceeded"

    @property
    def is_guardrail(self) -> bool:
        return self.code == "guardrail_violation"

    @property
    def is_policy_refusal(self) -> bool:
        """Refusals that must reach the student as-is (never retried around)."""
        return self.code in {"budget_exceeded", "guardrail_violation", "user_blocked",
                             "end_user_limit_reached", "insufficient_funds"}


@dataclass
class ChatResult:
    content: str
    model_requested: str
    model_served: str | None
    provider: str | None
    fallback: bool
    attempt_count: int | None
    request_id: str | None
    cost_usd: float
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    guardrails: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)

    def debug(self) -> dict[str, Any]:
        """What the on-screen Otari panel shows."""
        return {
            "model_requested": self.model_requested,
            "model_served": self.model_served,
            "provider": self.provider,
            "fallback": self.fallback,
            "attempt_count": self.attempt_count,
            "request_id": self.request_id,
            "cost_usd": self.cost_usd,
            "tokens": self.usage.get("total_tokens"),
            "tool_calls": [summarise_tool_call(t) for t in self.tool_calls],
            "guardrails": self.guardrails,
        }


@dataclass
class CodeResult:
    stdout: str
    stderr: str
    return_code: int
    request_id: str | None


def summarise_tool_call(t: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "type", "status", "query", "url", "server", "name", "exit_code", "error")
    out = {k: t[k] for k in keep if k in t}
    if t.get("type") == "web_search":
        out["sources"] = [s.get("url") for s in t.get("sources") or []][:3]
    if t.get("type") == "code_execution":
        out["stdout"] = (t.get("stdout") or "")[:400]
        out["stderr"] = (t.get("stderr") or "")[:400]
    if t.get("type") == "mcp":
        out["output"] = (t.get("output") or "")[:300]
    return out


def _detail_text(body: Any) -> str:
    if isinstance(body, dict):
        d = body.get("detail", body.get("error", body))
        if isinstance(d, list):
            return "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        if isinstance(d, dict):
            return str(d.get("message") or d)
        return str(d)
    return str(body)


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text
    code = resp.headers.get("Otari-Error-Code") or (body.get("code") if isinstance(body, dict) else None)
    retry = resp.headers.get("Retry-After")
    raise OtariError(
        resp.status_code,
        code,
        _detail_text(body)[:600],
        scope=resp.headers.get("Otari-Budget-Scope"),
        retry_after=int(retry) if retry and retry.isdigit() else None,
        request_id=resp.headers.get("Otari-Request-ID"),
    )


def _cost(usage: dict[str, Any]) -> float:
    try:
        return float(usage.get("cost_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def _message_text(choice_msg: dict[str, Any]) -> str:
    content = choice_msg.get("content")
    if isinstance(content, list):  # some providers return content parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


class Otari:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if transport is None and settings.mock:
            from .mock_gateway import MockGateway

            transport = MockGateway()
        self._client = httpx.AsyncClient(
            base_url=settings.otari_base_url,
            headers={
                "Authorization": f"Bearer {settings.otari_api_key or 'otk_mock'}",
                "Content-Type": "application/json",
                "User-Agent": "mollet/1.0",
            },
            timeout=settings.request_timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        """All traffic goes through here so network failures become OtariError too."""
        try:
            resp = await self._client.request(method, path, **kw)
        except httpx.TimeoutException as e:
            raise OtariError(504, "gateway_timeout", f"Otari did not answer in time ({type(e).__name__}).") from e
        except httpx.HTTPError as e:
            raise OtariError(503, "gateway_unreachable", f"Could not reach Otari ({type(e).__name__}).") from e
        _raise_for(resp)
        return resp

    # --- inference ----------------------------------------------------------------

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        user: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        mcp_server_ids: list[str] | None = None,
        guardrails: list[dict[str, Any]] | None = None,
        metadata: dict[str, str] | None = None,
        max_tokens: int | None = 700,
        temperature: float | None = 0.4,
        max_tool_iterations: int | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {"model": model, "messages": messages}
        if user:
            body["user"] = user  # end user on the service key -> that student's wallet
        if tools:
            body["tools"] = tools
        if mcp_server_ids:
            body["mcp_server_ids"] = mcp_server_ids
        if guardrails:
            body["guardrails"] = guardrails
        if metadata:
            body["metadata"] = metadata
        if max_tokens:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if max_tool_iterations:
            body["max_tool_iterations"] = max_tool_iterations

        resp = await self._request("POST", "/chat/completions", json=body)
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise OtariError(502, "provider_error", "The model returned no answer.",
                             request_id=resp.headers.get("Otari-Request-ID"))
        usage = data.get("usage") or {}
        gr_raw = resp.headers.get("Otari-Guardrails")
        try:
            guard = json.loads(gr_raw) if gr_raw else []
        except ValueError:
            guard = []
        attempts = resp.headers.get("Otari-Attempt-Count")
        return ChatResult(
            content=_message_text(choices[0].get("message") or {}).strip(),
            model_requested=model,
            model_served=resp.headers.get("Otari-Model") or data.get("model"),
            provider=resp.headers.get("Otari-Provider"),
            fallback=resp.headers.get("Otari-Fallback", "false").lower() == "true",
            attempt_count=int(attempts) if attempts and attempts.isdigit() else None,
            request_id=resp.headers.get("Otari-Request-ID"),
            cost_usd=_cost(usage),
            tool_calls=data.get("otari_tool_calls") or [],
            guardrails=guard if isinstance(guard, list) else [],
            usage=usage,
        )

    async def execute_code(self, code: str, *, user: str | None = None, timeout_s: int = 10) -> CodeResult:
        """POST /code/execute: run Python in Otari's sandbox, no model involved."""
        body: dict[str, Any] = {"code": code, "timeout_seconds": timeout_s}
        if user:
            body["user"] = user
        resp = await self._request("POST", "/code/execute", json=body)
        data = resp.json()
        return CodeResult(
            stdout=data.get("stdout") or "",
            stderr=data.get("stderr") or "",
            return_code=int(data.get("return_code") or 0),
            request_id=resp.headers.get("Otari-Request-ID"),
        )

    # --- wallets & budgets ----------------------------------------------------------

    async def end_user(self, external_id: str) -> dict[str, Any] | None:
        resp = await self._request("GET", "/end-users", params={"external_id": external_id})
        data = resp.json()
        if isinstance(data, list):
            return data[0] if data else None
        return data or None

    async def end_users(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/end-users", params={"limit": 1000})
        return resp.json()

    async def end_user_budgets(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/end-user-budgets")
        return resp.json()

    async def put_end_user(self, external_id: str, budget_id: str) -> dict[str, Any]:
        resp = await self._request(
            "PUT", "/end-users", params={"external_id": external_id}, json={"budget_id": budget_id}
        )
        return resp.json()

    async def key_budget(self) -> dict[str, Any]:
        resp = await self._request("GET", "/key/budget")
        return resp.json()

    # --- catalog reads (status page) ---------------------------------------------------

    async def get_json(self, path: str) -> Any:
        resp = await self._request("GET", path)
        return resp.json()
