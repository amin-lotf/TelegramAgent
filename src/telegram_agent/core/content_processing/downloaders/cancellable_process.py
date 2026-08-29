from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable

from telegram_agent.core.common.exceptions import SecondaryTaskCancelledError


class CancellableProcessRunner:
    def __init__(self, *, cancel_grace_seconds: float, poll_seconds: float = 0.25) -> None:
        self._cancel_grace_seconds = cancel_grace_seconds
        self._poll_seconds = poll_seconds

    def run(
        self,
        command: list[str],
        *,
        timeout_seconds: float,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if cancellation_requested is not None and cancellation_requested():
            raise SecondaryTaskCancelledError("Secondary task was cancelled")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate(process)
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            try:
                stdout, stderr = process.communicate(
                    timeout=min(self._poll_seconds, remaining)
                )
                return subprocess.CompletedProcess(
                    command,
                    process.returncode,
                    stdout,
                    stderr,
                )
            except subprocess.TimeoutExpired:
                if cancellation_requested is not None and cancellation_requested():
                    self._terminate(process)
                    raise SecondaryTaskCancelledError(
                        "Secondary task was cancelled"
                    )
            except BaseException:
                self._terminate(process)
                raise

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + self._cancel_grace_seconds
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        # Always drain the pipes and wait, including the race where the process
        # exits between poll() and killpg(). This prevents zombie children.
        try:
            process.communicate(timeout=max(self._cancel_grace_seconds, 1.0))
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
