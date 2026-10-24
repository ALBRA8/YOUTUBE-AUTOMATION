#!/usr/bin/env python3
"""
Tests unitarios y de integración para INT-042: Brand Profiles Persistentes
(Perfil de Canal / Marca)
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pytest
from starlette.testclient import TestClient

import database as db
import main
from services import brand_profiles as bp_svc


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_brand_profiles.db"
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield


def test_seed_starter_profile():
    profiles = bp_svc.list_brand_profiles()
    assert len(profiles) >= 1
    default_p = bp_svc.get_default_brand_profile()
    assert default_p is not None
    assert default_p["name"] == "Canal Principal / Shorts Virales"
    assert default_p["is_default"] is True
    assert default_p["subtitle_style"] == "hormozi"
    assert "es-ES-AlvaroNeural" in default_p["voice"]


def test_create_and_get_brand_profile():
    data = {
        "name": "Misterios Históricos 360",
        "niche": "Historia y Enigmas",
        "audience": "Aficionados a conspiraciones y misterios de 20 a 45 años",
        "tone": "Sombrío, pausado, dramático e intrigante",
        "visual_style": "cinematic",
        "voice": "es-MX-JorgeNeural",
        "tts_provider": "edge-tts",
        "subtitle_style": "mrbeast",
        "prompt_rules": "Comenzar siempre con una pregunta histórica sin resolver.",
        "is_default": False,
    }
    created = bp_svc.create_brand_profile(data)
    assert created["id"].startswith("bp_")
    assert created["name"] == "Misterios Históricos 360"
    assert created["niche"] == "Historia y Enigmas"
    assert created["visual_style"] == "cinematic"
    assert created["subtitle_style"] == "mrbeast"

    fetched = bp_svc.get_brand_profile(created["id"])
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["tone"] == data["tone"]


def test_create_requires_valid_name():
    with pytest.raises(ValueError):
        bp_svc.create_brand_profile({"name": "   "})


def test_default_profile_toggle():
    p1 = bp_svc.create_brand_profile({"name": "Canal 1", "is_default": True})
    assert p1["is_default"] is True

    p2 = bp_svc.create_brand_profile({"name": "Canal 2", "is_default": True})
    assert p2["is_default"] is True

    # p1 no debe seguir siendo default
    p1_updated = bp_svc.get_brand_profile(p1["id"])
    assert p1_updated["is_default"] is False

    # Switch default de vuelta a p1
    bp_svc.set_default_brand_profile(p1["id"])
    assert bp_svc.get_brand_profile(p1["id"])["is_default"] is True
    assert bp_svc.get_brand_profile(p2["id"])["is_default"] is False


def test_update_brand_profile():
    p = bp_svc.create_brand_profile({"name": "Original Name", "niche": "Tech"})
    updated = bp_svc.update_brand_profile(p["id"], {
        "name": "Updated Name",
        "subtitle_style": "neon",
        "visual_style": "anime",
    })
    assert updated["name"] == "Updated Name"
    assert updated["subtitle_style"] == "neon"
    assert updated["visual_style"] == "anime"


def test_delete_brand_profile_and_fallback():
    p1 = bp_svc.create_brand_profile({"name": "Canal Alpha", "is_default": False})
    p2 = bp_svc.create_brand_profile({"name": "Canal Beta", "is_default": True})

    ok = bp_svc.delete_brand_profile(p2["id"])
    assert ok is True
    assert bp_svc.get_brand_profile(p2["id"]) is None

    # Al eliminar el default, otro perfil pasa a ser default
    remaining_default = bp_svc.get_default_brand_profile()
    assert remaining_default is not None
    assert remaining_default["id"] == p1["id"] or remaining_default["is_default"] is True


def test_apply_brand_profile_to_project():
    profile = bp_svc.create_brand_profile({
        "name": "Finanzas Pro",
        "niche": "Finanzas e Inversiones",
        "tone": "Urgente y analítico",
        "visual_style": "hyperrealistic",
        "voice": "es-ES-AlvaroNeural",
        "tts_provider": "edge-tts",
        "subtitle_style": "hormozi",
        "prompt_rules": "Citar porcentajes o datos financieros verificables.",
    })

    proj = db.create_project(title="Proyecto de Finanzas")
    proj_id = proj["id"]
    applied = bp_svc.apply_brand_profile_to_project(profile["id"], proj_id)

    assert applied["id"] == proj_id
    assert applied["niche"] == "Finanzas e Inversiones"
    assert applied["voice"] == "es-ES-AlvaroNeural"
    assert applied["style"] == "hyperrealistic"
    assert applied["meta"]["subtitle_style"] == "hormozi"
    assert applied["meta"]["brand_profile_id"] == profile["id"]
    assert applied["meta"]["brand_profile"]["name"] == "Finanzas Pro"
    assert "Citar porcentajes" in applied["meta"]["prompt_rules"]


def test_format_prompt_directives():
    profile = {
        "name": "DocuSeries",
        "niche": "Documentales",
        "audience": "Público general",
        "tone": "Cinematográfico",
        "prompt_rules": "Regla 1: Ritmo lento.\nRegla 2: Voz en off profunda.",
    }
    directives = bp_svc.format_prompt_directives(profile)
    assert "DocuSeries" in directives
    assert "Documentales" in directives
    assert "Regla 1: Ritmo lento" in directives


def test_api_brand_profiles_endpoints():
    client = TestClient(main.app)

    # 1. List
    res = client.get("/api/brand-profiles")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["profiles"]) >= 1

    # 2. Create
    res_create = client.post("/api/brand-profiles", json={
        "name": "Canal Gaming Top",
        "niche": "Videojuegos",
        "voice": "es-MX-JorgeNeural",
        "subtitle_style": "tiktok",
    })
    assert res_create.status_code == 200
    p = res_create.json()["profile"]
    pid = p["id"]
    assert p["name"] == "Canal Gaming Top"
    assert p["subtitle_style"] == "tiktok"

    # 3. Get by ID
    res_get = client.get(f"/api/brand-profiles/{pid}")
    assert res_get.status_code == 200
    assert res_get.json()["profile"]["name"] == "Canal Gaming Top"

    # 4. Patch
    res_patch = client.patch(f"/api/brand-profiles/{pid}", json={
        "tone": "Eufórico y veloz",
        "subtitle_style": "boxed",
    })
    assert res_patch.status_code == 200
    assert res_patch.json()["profile"]["tone"] == "Eufórico y veloz"
    assert res_patch.json()["profile"]["subtitle_style"] == "boxed"

    # 5. Default toggle
    res_def = client.post(f"/api/brand-profiles/{pid}/default")
    assert res_def.status_code == 200
    assert res_def.json()["default_profile"]["is_default"] is True

    # 6. Directives
    res_dir = client.get(f"/api/brand-profiles/{pid}/directives")
    assert res_dir.status_code == 200
    assert "Canal Gaming Top" in res_dir.json()["directives"]

    # 7. Apply to project
    proj = db.create_project(title="Test Gaming Video")
    proj_id = proj["id"]
    res_apply = client.post(f"/api/brand-profiles/{pid}/apply", json={"project_id": proj_id})
    assert res_apply.status_code == 200
    assert res_apply.json()["applied_profile_id"] == pid
    assert res_apply.json()["project"]["meta"]["subtitle_style"] == "boxed"

    # 8. Delete
    res_del = client.delete(f"/api/brand-profiles/{pid}")
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] == pid

    # 9. Verify 404 after delete
    res_gone = client.get(f"/api/brand-profiles/{pid}")
    assert res_gone.status_code == 404

    # 10. Validation error on bad creation
    res_bad = client.post("/api/brand-profiles", json={"name": ""})
    assert res_bad.status_code == 400

    # 11. Project creation inheriting from brand profile
    new_bp = client.post("/api/brand-profiles", json={
        "name": "Canal Autos",
        "niche": "Automóviles",
        "voice": "es-ES-AlvaroNeural",
        "subtitle_style": "mrbeast",
        "visual_style": "cinematic"
    }).json()["profile"]
    res_new_proj = client.post("/api/projects", json={
        "mode": "idea",
        "idea": "Los 5 coches más rápidos del mundo",
        "brand_profile_id": new_bp["id"]
    })
    assert res_new_proj.status_code == 200
    created_proj = res_new_proj.json()
    assert created_proj["voice"] == "es-ES-AlvaroNeural"
    assert created_proj["style"] == "cinematic"
    assert created_proj["meta"]["subtitle_style"] == "mrbeast"
    assert created_proj["meta"]["brand_profile_id"] == new_bp["id"]
    assert created_proj["brand_profile_id"] == new_bp["id"]


if __name__ == "__main__":
    import tempfile
    td = tempfile.mkdtemp()
    db.DB_PATH = Path(td) / "test.db"
    db.init_db()
    test_seed_starter_profile()
    print("[OK] test_seed_starter_profile")
    test_create_and_get_brand_profile()
    print("[OK] test_create_and_get_brand_profile")
    test_create_requires_valid_name()
    print("[OK] test_create_requires_valid_name")
    test_default_profile_toggle()
    print("[OK] test_default_profile_toggle")
    test_update_brand_profile()
    print("[OK] test_update_brand_profile")
    test_delete_brand_profile_and_fallback()
    print("[OK] test_delete_brand_profile_and_fallback")
    test_apply_brand_profile_to_project()
    print("[OK] test_apply_brand_profile_to_project")
    test_format_prompt_directives()
    print("[OK] test_format_prompt_directives")
    test_api_brand_profiles_endpoints()
    print("[OK] test_api_brand_profiles_endpoints")
    print("\nTODOS LOS TESTS DE BRAND PROFILES PASARON AL 100% (9/9).")
