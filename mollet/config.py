"""Runtime settings, read once from the environment (and a local .env file).

Every Otari-facing name lives here so the README can point at one file:
model / routing-policy names, the MCP server id, guardrail profiles and the
demo budget numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, "").split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    # --- Otari gateway -------------------------------------------------------
    # The OpenAI-compatible base URL. EU accounts use https://eu.api.otari.ai/api/v1
    otari_base_url: str = field(default_factory=lambda: _env("OTARI_BASE_URL", "https://api.otari.ai/api/v1").rstrip("/"))
    # A *service key* (created with "Service key" ticked under API keys -> Advanced).
    otari_api_key: str = field(default_factory=lambda: _env("OTARI_API_KEY"))
    request_timeout_s: float = field(default_factory=lambda: _env_float("OTARI_TIMEOUT_S", 90.0))

    # --- Models (open-weight) --------------------------------------------------
    # Hint levels 1-3 go to the Hinter. Point this at a routing policy name
    # (fallback chain) once it exists in the dashboard; a plain model id works too.
    hinter_model: str = field(default_factory=lambda: _env("MOLLET_HINTER_MODEL", "mollet-hinter"))
    # Hint levels 4-5 go to the Mentor: a stronger model behind a
    # "tier down when the budget fills up" policy.
    mentor_model: str = field(default_factory=lambda: _env("MOLLET_MENTOR_MODEL", "mollet-mentor"))
    # The Grader: a different open-weight *coding* model.
    grader_model: str = field(default_factory=lambda: _env("MOLLET_GRADER_MODEL", "mollet-grader"))
    # Cheap model the app uses for its own "does this hint leak the answer?" check.
    # Empty = use the heuristic check only (no extra spend).
    leak_check_model: str = field(default_factory=lambda: _env("MOLLET_LEAK_CHECK_MODEL"))

    # --- Otari tools -------------------------------------------------------------
    # Workspace MCP server id (Tools -> MCP servers). Empty = MCP off, history is
    # inlined into the prompt instead.
    mcp_server_id: str = field(default_factory=lambda: _env("MOLLET_MCP_SERVER_ID"))
    web_search_enabled: bool = field(default_factory=lambda: _env_bool("MOLLET_WEB_SEARCH", True))
    grader_uses_code_tool: bool = field(default_factory=lambda: _env_bool("MOLLET_GRADER_CODE_TOOL", True))
    code_timeout_s: int = field(default_factory=lambda: int(_env_float("MOLLET_CODE_TIMEOUT_S", 10)))

    # --- Guardrails ----------------------------------------------------------------
    # Request-level guardrail profiles sent in block mode on every student message,
    # e.g. "prompt-injection". Organization-mandated guardrails apply on top.
    guardrail_profiles: list[str] = field(default_factory=lambda: _env_list("MOLLET_GUARDRAILS"))
    # App rule (not Otari): a local regex PII pre-check before anything leaves the
    # server. Off by default so the Otari guardrail is what blocks on camera.
    app_pii_precheck: bool = field(default_factory=lambda: _env_bool("MOLLET_APP_PII_PRECHECK", False))

    # --- Display-only numbers --------------------------------------------------------
    # Used for the wallet bar when Otari cannot report a limit (e.g. before the
    # end-user budget is readable). The *real* cap is the Otari budget.
    fallback_wallet_usd: float = field(default_factory=lambda: _env_float("MOLLET_WALLET_USD", 0.05))
    class_budget_usd: float = field(default_factory=lambda: _env_float("MOLLET_CLASS_BUDGET_USD", 1.00))

    # --- MCP server (served by this same app at /classroom/mcp) ------------------------
    mcp_token: str = field(default_factory=lambda: _env("MOLLET_MCP_TOKEN"))
    mcp_allowed_hosts: list[str] = field(default_factory=lambda: _env_list("MOLLET_MCP_ALLOWED_HOSTS"))

    # --- App ----------------------------------------------------------------------------
    db_path: Path = field(default_factory=lambda: Path(_env("MOLLET_DB", str(ROOT / "mollet.db"))))
    # Offline fake gateway for UI work and tests. Never use for the demo video.
    mock: bool = field(default_factory=lambda: _env_bool("MOLLET_MOCK", False))

    @property
    def configured(self) -> bool:
        return bool(self.otari_api_key) or self.mock


settings = Settings()
