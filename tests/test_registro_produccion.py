# -*- coding: utf-8 -*-
"""PASO 2 · Registro local de producciones y convención de nombres.

Hermético: solo I/O bajo un OUTPUT_DIR/DATA_DIR aislado (monkeypatch de
config, igual que hace tests/conftest.py). Flow/NotebookLM NUNCA se tocan:
la creación de proyecto es un doble; los avatares van por universos.

Decisiones del dueño que se blindan:
  - avatares SOLO en Flow (sin cuaderno de avatares);
  - UN cuaderno de NotebookLM por NICHO;
  - UN proyecto de Flow por historia;
  - la clave es el ID estable; los nombres son etiquetas;
  - idempotencia: con flow_project_id NO se crea otro proyecto.

Ejecutar: python3 -m pytest tests/test_registro_produccion.py -q
"""
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import config  # noqa: E402
from services import registro_produccion as rp  # noqa: E402
from services import universos  # noqa: E402


@pytest.fixture()
def aislado(tmp_path, monkeypatch):
    """OUTPUT_DIR/DATA_DIR aislados para ESTA prueba (lectura en llamada)."""
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "OUTPUT_DIR", data / "output")
    return tmp_path


# ── 2.3 · convención de nombres determinista ─────────────────────────

def test_formato_exacto():
    assert rp.nombre_produccion("Frutinovelas", 3,
                                "La receta del caos") == \
        "FRUTINOVELAS · S003 · La receta del caos"


def test_numero_minimo_y_ceros():
    assert "S001" in rp.nombre_produccion("nicho", 1, "t")
    assert "S012" in rp.nombre_produccion("nicho", 12, "t")


def test_saneamiento_titulo_y_nicho():
    n = rp.nombre_produccion("  fruti · novelas  ", 2, "  Título\ncon · guías  ")
    assert n == "FRUTI NOVELAS · S002 · Título con guías"


def test_longitud_maxima_con_ellipsis():
    n = rp.nombre_produccion("FRUTINOVELAS", 3, "x" * 200, max_len=80)
    assert len(n) <= 80
    assert n.endswith("…")
    assert n.startswith("FRUTINOVELAS · S003 · ")


def test_sanea_sin_titulo_no_doble_separador():
    assert rp.nombre_produccion("N", 1, "") == "N · S001"


# ── 2.1 · registro por producción ─────────────────────────────────────

def test_registro_path_seguridad_rechaza_traversal_y_separadores(aislado):
    """R2 · Seguridad: rechaza ../, separadores, rutas absolutas, vacíos y largos."""
    with pytest.raises(ValueError, match=r"no puede contener '\.\.'|separadores"):
        rp.registro_path("../escape")
    with pytest.raises(ValueError, match=r"no puede contener '\.\.'|separadores"):
        rp.registro_path("sub/folder")
    with pytest.raises(ValueError, match=r"no puede contener '\.\.'|separadores"):
        rp.registro_path("sub\\folder")
    with pytest.raises(ValueError, match="absoluta|separadores"):
        rp.registro_path("/etc/passwd")
    with pytest.raises(ValueError, match="absoluta|separadores"):
        rp.registro_path("C:\\Windows\\System32")
    with pytest.raises(ValueError, match="vacío"):
        rp.registro_path("")
    with pytest.raises(ValueError, match="demasiado largo"):
        rp.registro_path("a" * 81)


def test_crear_concurrente_sin_carreras(aislado):
    """R3 · Concurrencia: hilos simultáneos en el mismo nicho no duplican numero_serie."""
    import concurrent.futures

    nicho = "nicho_concurrente"
    total = 10

    def trabajador(i):
        return rp.crear(f"PROD_{i}", nicho, f"Historia {i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futuros = [executor.submit(trabajador, i) for i in range(total)]
        resultados = [f.result() for f in concurrent.futures.as_completed(futuros)]

    numeros = [r["numero_serie"] for r in resultados]
    assert len(numeros) == total
    assert len(set(numeros)) == total, f"Números duplicados detectados: {numeros}"
    assert set(numeros) == set(range(1, total + 1))


def test_json_corrupto_registra_aviso_y_no_reutiliza_numero(aislado, caplog):
    """R3 · JSON corrupto: emite warning y no reutiliza el número."""
    import logging

    rp.crear("P1", "nicho_corrupto", "Historia 1")
    rp.crear("P2", "nicho_corrupto", "Historia 2")
    assert rp.siguiente_numero("nicho_corrupto") == 3

    # Corromper el archivo de P2
    p2_file = rp.registro_path("P2")
    p2_file.write_text('{"production_id": "P2", "numero_serie": 2, CORRUPTO...', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        sig = rp.siguiente_numero("nicho_corrupto")

    # El siguiente número sigue siendo 3 (no reutiliza el 2)
    assert sig == 3
    # Registró el aviso
    assert any("JSON corrupto detectado" in record.message for record in caplog.records)


def test_crear_y_leer_roundtrip(aislado):
    rp.crear("P1", "frutinovelas", "La receta del caos",
             nicho_nombre="Frutinovelas")
    reg = rp.leer("P1")
    assert reg["production_id"] == "P1"
    assert reg["nicho_id"] == "frutinovelas"
    assert reg["numero_serie"] == 1
    assert reg["nombre_flow"] == "FRUTINOVELAS · S001 · La receta del caos"
    assert reg["flow_project_id"] is None
    assert reg["estado"] == "DRAFT"
    assert "creado_en" in reg and "actualizado_en" in reg


def test_campos_obligatorios_del_registro(aislado):
    rp.crear("P1", "nicho", "título")
    reg = rp.leer("P1")
    for campo in ("production_id", "nicho_id", "titulo_historia",
                  "numero_serie", "nombre_flow", "flow_project_id",
                  "flow_project_nombre_observado", "notebook_id_nicho",
                  "estado"):
        assert campo in reg, campo


def test_numero_serie_secuencial_por_nicho(aislado):
    rp.crear("P1", "frutinovelas", "a")
    rp.crear("P2", "frutinovelas", "b")
    rp.crear("P3", "microdramas", "c")
    assert rp.leer("P1")["numero_serie"] == 1
    assert rp.leer("P2")["numero_serie"] == 2
    assert rp.leer("P3")["numero_serie"] == 1   # otro nicho, serie propia


def test_crear_es_idempotente_con_numero_previo(aislado):
    rp.crear("P1", "frutinovelas", "a")
    rp.crear("P1", "frutinovelas", "a")   # re-crear no re-numera
    assert rp.leer("P1")["numero_serie"] == 1


def test_guardar_sin_id_estable_falla(aislado):
    with pytest.raises(ValueError):
        rp.guardar({"nicho_id": "x"})


# ── 2.2 · registro por nicho: UN cuaderno por nicho ──────────────────

def test_registrar_nicho_y_leer(aislado):
    rp.registrar_nicho("frutinovelas", "nb-123",
                       "NICHO · Frutinovelas")
    nicho = rp.registro_nicho("frutinovelas")
    assert nicho["notebook_id"] == "nb-123"
    assert nicho["nombre_cuaderno"] == "NICHO · Frutinovelas"


def test_un_solo_cuaderno_por_nicho_reemplaza(aislado):
    rp.registrar_nicho("frutinovelas", "nb-1", "v1")
    rp.registrar_nicho("frutinovelas", "nb-2", "v2")
    assert rp.registro_nicho("frutinovelas")["notebook_id"] == "nb-2"


def test_propaga_notebook_a_la_produccion(aislado):
    rp.registrar_nicho("frutinovelas", "nb-9", "NICHO · Frutinovelas")
    rp.crear("P1", "frutinovelas", "a")
    reg = rp.propaga_notebook("P1")
    assert reg["notebook_id_nicho"] == "nb-9"


# ── 2.4 · avatares: SOLO Flow, sin cuaderno ──────────────────────────

def test_vincular_avatar_delega_en_universos(aislado, monkeypatch):
    recibido = {}

    def doble(lib_id, flow_project_id, flow_character_id):
        recibido.update(lib=lib_id, p=flow_project_id, c=flow_character_id)
        return {"id": lib_id, "flow_character_id": flow_character_id}

    monkeypatch.setattr(universos, "vincular_flow", doble)
    rp.vincular_avatar_flow("cocardo", "proj-1", "char-7")
    assert recibido == {"lib": "cocardo", "p": "proj-1", "c": "char-7"}


def test_avatar_no_crea_cuaderno(aislado, monkeypatch):
    """Los avatares viven en la biblioteca (flow_character_id) y NUNCA
    obtienen cuaderno: registro_nichos.json no se crea/toca."""
    monkeypatch.setattr(universos, "vincular_flow",
                        lambda *a: {"id": a[0]})
    ruta = aislado / "data" / "registro_nichos.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"frutinovelas": {"notebook_id": "nb-1"}}),
                    encoding="utf-8")
    antes = ruta.read_text(encoding="utf-8")
    rp.vincular_avatar_flow("cocardo", "proj-1", "char-7")
    assert ruta.read_text(encoding="utf-8") == antes


# ── 2.5 · idempotencia de la vinculación con Flow ────────────────────

def test_vinculacion_crea_una_sola_vez(aislado):
    rp.crear("P1", "frutinovelas", "a")
    llamadas = []

    def doble_crear(nombre_flow):
        llamadas.append(nombre_flow)
        return {"flow_project_id": "flow-abc", "nombre_observado": nombre_flow}

    r1 = rp.registrar_flow_proyecto("P1", doble_crear,
                                    nombres_soportados="SOPORTADO")
    r2 = rp.registrar_flow_proyecto("P1", doble_crear,
                                    nombres_soportados="SOPORTADO")
    assert r1["estado"] == "VINCULADO"
    assert r2["estado"] == "YA_VINCULADO"
    assert len(llamadas) == 1                       # SOLO un proyecto
    assert rp.leer("P1")["flow_project_id"] == "flow-abc"


def test_nombre_observado_solo_si_sonda_soporta(aislado):
    rp.crear("P1", "frutinovelas", "a")
    rp.crear("P2", "frutinovelas", "b")

    def doble(nombre_flow):
        return {"flow_project_id": f"flow-{nombre_flow[:6]}",
                "nombre_observado": nombre_flow}

    rp.registrar_flow_proyecto("P1", doble, nombres_soportados="SOPORTADO")
    rp.registrar_flow_proyecto("P2", doble, nombres_soportados="NO_SOPORTADO")
    assert rp.leer("P1")["flow_project_nombre_observado"] == \
        rp.leer("P1")["nombre_flow"]
    assert rp.leer("P2")["flow_project_nombre_observado"] is None
    limit = rp.leer("P2")["limitaciones"]
    assert any("NO_SOPORTADO" in x for x in limit)


def test_registrar_flow_proyecto_sin_id_devuelve_error(aislado):
    """R1 · Bug: si crear_proyecto no entrega id, devuelve ERROR y anota limitación."""
    rp.crear("P1", "frutinovelas", "a")
    res = rp.registrar_flow_proyecto("P1", lambda n: {})
    assert res["estado"] == "ERROR"
    assert res["flow_project_id"] is None
    reg = rp.leer("P1")
    assert reg["flow_project_id"] is None
    assert any("no entrego flow_project_id" in x or "no entregó flow_project_id" in x for x in reg["limitaciones"])


def test_vinculacion_sin_registro_falla(aislado):
    with pytest.raises(ValueError):
        rp.registrar_flow_proyecto("NO_EXISTE", lambda n: {})


# ── 2.x · listado (base del endpoint 3.2) ────────────────────────────

def test_listar_producciones(aislado):
    rp.registrar_nicho("frutinovelas", "nb-1", "NICHO · Frutinovelas")
    rp.crear("P1", "frutinovelas", "a")
    rp.crear("P2", "microdramas", "b")
    lista = rp.listar_producciones()
    ids = {x["production_id"] for x in lista}
    assert ids == {"P1", "P2"}
    p1 = next(x for x in lista if x["production_id"] == "P1")
    assert p1["notebook_id_nicho"] == "nb-1"
    assert p1["flow_project_id"] is None
    assert p1["nombre_flow"].startswith("FRUTINOVELAS · S001 · ")


def test_listar_sin_output_devuelve_vacia(aislado):
    assert rp.listar_producciones() == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
