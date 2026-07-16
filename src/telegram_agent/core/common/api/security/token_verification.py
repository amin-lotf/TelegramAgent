from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status
from starlette.requests import Request




class VerifyApiToken:
    def __init__(self, expected_token: str | None) -> None:
        self.expected_token = expected_token
    async def __call__(
        self,
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(auto_error=False)),
        ] = None,
    ) -> None:
        if not self.expected_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server misconfigured: AUTH_SERVICE_TOKEN is not set",
            )

        # Swagger UI "Authorize" uses the HTTPBearer scheme, which yields token-only credentials.
        if credentials and credentials.credentials == self.expected_token:
            return

        authorization = request.headers.get("authorization")
        if self._is_authorized(authorization, self.expected_token):
            return

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )

    def _is_authorized(self,authorization: str | None, token: str) -> bool:
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

