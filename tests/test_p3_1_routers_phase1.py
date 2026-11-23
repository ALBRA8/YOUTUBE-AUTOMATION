"""
Test P3-1: Verificación de routers modulares (Fase 1: /api/niches).
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from backend.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_niches_routes_registered_via_router():
    """P3-1: Los endpoints de nichos deben estar registrados en la app."""
    paths = app.openapi()["paths"]
    assert "/api/niches" in paths
    assert "/api/niches/templates" in paths
    assert "/api/niches/templates/{tid}" in paths


def test_niches_list_endpoint(client):
    """P3-1: GET /api/niches responde 200 y lista de nichos."""
    res = client.get("/api/niches")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_niches_templates_crud(client):
    """P3-1: Ciclo completo CRUD de templates a través del APIRouter."""
    # 1. List
    res_list = client.get("/api/niches/templates")
    assert res_list.status_code == 200
    initial_templates = res_list.json()

    # 2. Create
    payload = {
        "name": "Nicho Test P3-1",
        "description": "Nicho para verificación de migración APIRouter",
        "style": "cinematic",
        "voice": "es-ES-Neural2-F"
    }
    res_post = client.post("/api/niches/templates", json=payload)
    assert res_post.status_code == 200
    saved = res_post.json()
    tid = saved.get("id") or saved.get("name")
    assert tid is not None

    # 3. Delete
    res_del = client.delete(f"/api/niches/templates/{tid}")
    assert res_del.status_code == 200
    assert res_del.json().get("ok") is True

    # 4. Delete missing returns 404
    res_del_404 = client.delete("/api/niches/templates/non_existent_tid_999")
    assert res_del_404.status_code == 404


if __name__ == "__main__":
    test_niches_routes_registered_via_router()
    c = TestClient(app, raise_server_exceptions=False)
    test_niches_list_endpoint(c)
    test_niches_templates_crud(c)
    print("PASS: test_p3_1_routers_phase1")
