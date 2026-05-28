from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB = "runtime/advanced_agent.sqlite"
DEFAULT_CONFIG = ".env.json"
DEFAULT_LOG_DIR = "runtime/codex_interactive"
DEFAULT_SESSION_TITLE = "default"
DEFAULT_SCOPE = "project:advanced_agent"
DEFAULT_MCP_SERVER_NAME = "advanced-agent"


def env_default(name: str, fallback: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else fallback


def default_db() -> str:
    return env_default("ADVANCED_AGENT_DB", DEFAULT_DB)


def default_config() -> str:
    return env_default("ADVANCED_AGENT_CONFIG", DEFAULT_CONFIG)


def default_log_dir() -> str:
    return env_default("ADVANCED_AGENT_LOG_DIR", DEFAULT_LOG_DIR)


def default_session_title() -> str:
    return env_default("ADVANCED_AGENT_SESSION_TITLE", DEFAULT_SESSION_TITLE)


def default_scope() -> str:
    return env_default("ADVANCED_AGENT_SCOPE", DEFAULT_SCOPE)


def default_mcp_server_name() -> str:
    return env_default("ADVANCED_AGENT_MCP_SERVER", DEFAULT_MCP_SERVER_NAME)


def project_root() -> str:
    return str(Path.cwd())
