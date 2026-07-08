from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken


def set_expected_api_token(app: FastAPI, token: str) -> None:
    for dependant in _iter_dependants(app):
        _patch_verify_token(dependant.dependencies, token)


def _iter_dependants(app: FastAPI) -> Iterable:
    for route in app.router.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            yield dependant

        if type(route).__name__ == "_IncludedRouter":
            for context in route.effective_route_contexts():
                yield context.dependant


def _patch_verify_token(dependencies: list, token: str) -> None:
    for dependency in dependencies:
        call = getattr(dependency, "call", None)
        if isinstance(call, VerifyApiToken):
            call.expected_token = token

        nested = getattr(dependency, "dependencies", None)
        if nested:
            _patch_verify_token(nested, token)
