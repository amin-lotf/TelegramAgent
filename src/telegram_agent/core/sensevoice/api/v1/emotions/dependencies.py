from fastapi import Request

from telegram_agent.core.sensevoice.runtime import SenseVoiceRuntime


def get_sensevoice_runtime(request: Request) -> SenseVoiceRuntime:
    return request.app.state.sensevoice_runtime
