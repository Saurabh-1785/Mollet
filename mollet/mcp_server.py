"""Classroom MCP server: lets the model look up a problem and a student's past mistakes.

Served by the same app over streamable HTTP at `/classroom/mcp`, so it reads the
same SQLite file. Register its public HTTPS URL in the Otari workspace
(Tools -> MCP servers); hint requests then pass that server's id in
`mcp_server_ids`, and Otari's gateway calls these tools during the tool loop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import db, problems
from .config import settings


def _security() -> TransportSecuritySettings:
    if settings.mcp_allowed_hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=[f"https://{h}" for h in settings.mcp_allowed_hosts],
        )
    # Server-to-server traffic from the Otari gateway (not a browser); the bearer
    # token below is the access control.
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


mcp = FastMCP(
    "mollet-classroom",
    instructions=(
        "Classroom records for Mollet. Use get_student_history to find a student's past "
        "mistakes and get_problem to read the problem they are working on. Never reveal "
        "hidden tests or full solutions."
    ),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def get_problem(problem_id: str) -> dict[str, Any]:
    """Get a practice problem's statement, the concept it practises and one example.

    Hidden tests are never included."""
    p = problems.get(problem_id)
    if not p:
        return {"error": f"unknown problem_id {problem_id!r}",
                "known": [x.id for x in problems.PROBLEMS]}
    return problems.public_view(p)


@mcp.tool()
def get_student_history(student_id: str) -> dict[str, Any]:
    """Get a student's recent mistakes (from graded submissions), which problems they
    solved, and how high up the hint ladder they climbed on each problem."""
    if not db.student(student_id):
        return {"error": f"unknown student_id {student_id!r}"}
    return db.history(student_id)


class BearerGuard:
    """Optional shared-secret check (MOLLET_MCP_TOKEN). Otari sends the token
    configured on the workspace MCP server as `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.token:
            auth = Request(scope).headers.get("authorization", "")
            if auth != f"Bearer {self.token}":
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class _Endpoint:
    """ASGI endpoint that forwards to the session manager of the running app.

    A session manager can run only once, so each app lifespan starts a fresh one
    (see `running()`); this keeps restarts and test clients working."""

    manager: StreamableHTTPSessionManager | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.manager is None:
            await JSONResponse({"error": "MCP server not running"}, status_code=503)(scope, receive, send)
            return
        await self.manager.handle_request(scope, receive, send)


_endpoint = _Endpoint()


@asynccontextmanager
async def running() -> AsyncIterator[None]:
    manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=True,
        stateless=True,
        security_settings=_security(),
    )
    async with manager.run():
        _endpoint.manager = manager
        try:
            yield
        finally:
            _endpoint.manager = None


def asgi_app() -> ASGIApp:
    """Mounted at /classroom, so the MCP URL is <host>/classroom/mcp."""
    app = Starlette(routes=[Route("/mcp", endpoint=_endpoint, methods=["GET", "POST", "DELETE"])])
    return BearerGuard(app, settings.mcp_token)
