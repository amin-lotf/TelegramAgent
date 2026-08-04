from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class GpuWorkloadPermanentError(RuntimeError):
    """The same input must not be retried without being changed."""


class GpuWorkloadRetryableError(RuntimeError):
    """The workload may succeed when started again in a fresh process."""


class GpuWorkloadHandler(Protocol):
    execute: Callable[..., None]
