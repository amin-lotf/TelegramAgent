from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
import uvicorn


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class HttpResponse:
    status_code: int
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class LiveServer:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.host = "127.0.0.1"
        self.port = _find_free_port()
        self.base_url = f"http://{self.host}:{self.port}"
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None

    def __enter__(self) -> "LiveServer":
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if server.started:
                self._server = server
                self._thread = thread
                return self
            if not thread.is_alive():
                raise RuntimeError("The local uvicorn test server exited before startup completed.")
            time.sleep(0.05)

        raise RuntimeError("Timed out waiting for the local uvicorn test server to start.")

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        body = None
        request_headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return HttpResponse(
                    status_code=response.getcode(),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
            )
