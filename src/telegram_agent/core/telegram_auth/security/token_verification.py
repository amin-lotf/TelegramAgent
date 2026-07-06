from fastapi import HTTPException,Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status
from starlette.requests import Request
from starlette.websockets import WebSocket

from telegram_agent.core.telegram_auth.common.settings import settings

_bearer = HTTPBearer(auto_error=False)


def _is_authorized(authorization: str | None, token: str) -> bool:
    if not authorization:
        return False
    provided = authorization.strip()
    if not provided:
        return False

    # Accept either a raw token or a standard "Bearer <token>" header.
    if provided == token:
        return True
    if provided.lower().startswith("bearer "):
        return provided[7:].strip() == token
    return False


def verify_api_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    token = settings.auth_service_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: AUTH_SERVICE_TOKEN is not set",
        )

    # Swagger UI "Authorize" uses the HTTPBearer scheme, which yields token-only credentials.
    if credentials and credentials.credentials == token:
        return

    authorization = request.headers.get("authorization")
    if _is_authorized(authorization, token):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )


async def verify_websocket_token(websocket: WebSocket) -> None:
    token = settings.chatbot_api_token
    if not token:
        await websocket.close(code=1011, reason="Server misconfigured")
        raise RuntimeError("Server misconfigured: TOKEN is not set")

    authorization = websocket.headers.get("authorization")
    if not _is_authorized(authorization, token):
        await websocket.close(code=1008, reason="Unauthorized")
        raise RuntimeError("Unauthorized WebSocket connection")
