from __future__ import annotations


class AdvancedAgentError(Exception):
    """Base error for runtime-level failures."""


class ConfigError(AdvancedAgentError):
    pass


class StoreError(AdvancedAgentError):
    pass


class AuditRejected(AdvancedAgentError):
    pass


class BackendUnavailable(AdvancedAgentError):
    pass
