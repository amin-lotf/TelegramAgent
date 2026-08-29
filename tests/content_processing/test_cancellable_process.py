from __future__ import annotations

import sys

import pytest

from telegram_agent.core.common.exceptions import SecondaryTaskCancelledError
from telegram_agent.core.content_processing.downloaders.cancellable_process import (
    CancellableProcessRunner,
)


def test_cancellation_terminates_running_process_group() -> None:
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(SecondaryTaskCancelledError):
        CancellableProcessRunner(
            cancel_grace_seconds=0.2,
            poll_seconds=0.02,
        ).run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=5,
            cancellation_requested=cancelled,
        )
