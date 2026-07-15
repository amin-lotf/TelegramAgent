from __future__ import annotations


class DashboardError(Exception):
    """Base class for expected dashboard failures."""


class DataSourceUnavailableError(DashboardError):
    def __init__(self, source: str, reason: str = "Database query unavailable") -> None:
        super().__init__(reason)
        self.source = source
        self.reason = reason


class FilterUnavailableError(DashboardError):
    def __init__(self, source: str) -> None:
        super().__init__(f"The requested filter requires the unavailable {source} database")
        self.source = source


class InvalidCursorError(DashboardError):
    """Raised when a pagination cursor is malformed, tampered with, or stale."""
