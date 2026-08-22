from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_and_readiness_without_model() -> None:
    app = create_app(Settings(skip_model_load=True, madlad_adapter_dir="/adapters"))
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert not health.json()["model_ready"]
    assert ready.json() == {"ready": False}


def test_translate_and_reload_return_503_until_ready() -> None:
    app = create_app(Settings(skip_model_load=True))
    with TestClient(app) as client:
        translate = client.post(
            "/v1/translate", json={"texts": ["Hello"], "target_lang": "fa"}
        )
        reload_response = client.post("/v1/reload-adapter")
    assert translate.status_code == 503
    assert reload_response.status_code == 503


def test_languages_exposes_known_aliases() -> None:
    app = create_app(Settings(skip_model_load=True))
    with TestClient(app) as client:
        response = client.get("/languages")
    assert response.status_code == 200
    assert response.json()["aliases"]["persian"] == "fa"
