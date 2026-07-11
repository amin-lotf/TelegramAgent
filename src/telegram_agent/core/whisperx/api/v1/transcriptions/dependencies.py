from fastapi import Request

from telegram_agent.core.whisperx.runtime import WhisperXRuntime


def get_whisperx_runtime(request: Request) -> WhisperXRuntime:
    return request.app.state.whisperx_runtime
