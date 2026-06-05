from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB = "runtime/advanced_agent.sqlite"
DEFAULT_MEMORY_DB = "memory/longterm.sqlite"
DEFAULT_RAWTAIL_DB = "memory/rawtail.sqlite"
DEFAULT_RAWTAIL_MAX_BYTES = 10 * 1024 * 1024
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


def default_memory_db() -> str:
    return env_default("ADVANCED_AGENT_MEMORY_DB", DEFAULT_MEMORY_DB)


def default_rawtail_db() -> str:
    return env_default("ADVANCED_AGENT_RAWTAIL_DB", DEFAULT_RAWTAIL_DB)


def default_rawtail_max_bytes() -> int:
    value = env_default("ADVANCED_AGENT_RAWTAIL_MAX_BYTES", str(DEFAULT_RAWTAIL_MAX_BYTES))
    try:
        return max(0, int(value))
    except ValueError:
        return DEFAULT_RAWTAIL_MAX_BYTES


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
