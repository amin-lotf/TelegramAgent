"""Collect the standalone container tests in the repository test suite."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "docker" / "madlad"
_REPO_ROOT = _ROOT.parents[1]
for _path in (str(_REPO_ROOT / "src"), str(_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _load(module_name: str, filename: str):
    path = _ROOT / "tests" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_languages = _load("telegram_madlad_languages_tests", "test_languages.py")
_routes = _load("telegram_madlad_routes_tests", "test_routes.py")

for _module in (_languages, _routes):
    for _name, _value in vars(_module).items():
        if _name.startswith("test_"):
            globals()[_name] = _value


def test_madlad_compose_uses_container_env_file_without_interpolation() -> None:
    compose = (_ROOT / "madlad-docker-compose.yml").read_text(encoding="utf-8")

    assert "env_file:" in compose
    assert "path: .env.madlad.docker" in compose
    assert 'profiles: ["madlad"]' in compose
    assert "${MADLAD_" not in compose
    assert '"127.0.0.1:8003:8000"' in compose


def test_madlad_make_targets_use_standard_compose_command() -> None:
    makefile = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "MADLAD_COMPOSE" not in makefile
    assert "MADLAD_ENV_ARG" not in makefile
    assert "$(COMPOSE) --profile madlad up -d madlad" in makefile
    assert "$(COMPOSE) --profile madlad stop madlad" in makefile
    assert "$(COMPOSE) build madlad" in makefile
