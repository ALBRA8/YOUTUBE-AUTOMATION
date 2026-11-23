# -*- coding: utf-8 -*-
"""P2-5 · Regresión del protocolo Fase 3 (hermético, sin servidor).

Verifica los CRITERIOS codificados con datos sintéticos: PASS y FAIL, y que
el script exista sin ejecutar nada contra Flow real (NOT_DEMONSTRATED).

Ejecutar: python3 -m pytest tests/test_p2_5_protocolo_fase3.py -q
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from fase3_aceptacion import CRITERIOS, evalua_protocolo, redacta  # noqa: E402


def _registro(nicho="nichoA", estado="ready", ph=0, qa=0, manual=False,
              revisada=True):
    return {"proyecto": "abc123", "nicho": nicho, "estado": estado,
            "placeholders": ph, "qa_errors": qa,
            "intervencion_manual": manual, "revisada_por_dueno": revisada}


def test_protocolo_pass_con_datos_ideales():
    regs = [_registro(nicho="nichoA" if i < 5 else "nichoB",
                      manual=(i == 0)) for i in range(10)]
    res = evalua_protocolo(regs)
    assert res["veredicto"] == "PASS", res
    assert res["videos"] == 10 and len(res["nichos"]) == 2
    assert all(res["checks"].values())


def test_protocolo_falla_por_placeholders():
    regs = [_registro() for _ in range(10)]
    regs[0]["placeholders"] = 2  # > CRITERIOS.max_placeholders (0)
    res = evalua_protocolo(regs)
    assert res["veredicto"] == "FAIL"
    assert res["checks"]["cero_placeholders"] is False


def test_protocolo_falla_por_ready_con_qa_error():
    regs = [_registro() for _ in range(10)]
    regs[1]["qa_errors"] = 1  # ready con fallo QA de severidad error
    res = evalua_protocolo(regs)
    assert res["veredicto"] == "FAIL"
    assert res["checks"]["cero_ready_con_qa_error"] is False


def test_protocolo_falla_por_intervencion_manual_excesiva():
    regs = [_registro(manual=True) for _ in range(10)]  # 0/8 sin manual
    res = evalua_protocolo(regs)
    assert res["veredicto"] == "FAIL"
    assert res["checks"]["meta_sin_intervencion"] is False


def test_reporte_redacta_veredicto_y_criterios():
    regs = [_registro(nicho="nichoA" if i < 5 else "nichoB")
            for i in range(10)]
    texto = redacta(evalua_protocolo(regs))
    assert "VEREDICTO: **PASS**" in texto
    assert "meta_sin_intervencion" in texto


def test_script_existe_y_no_se_autoejecuta():
    """El protocolo está PREPARADO pero NO ejecutado con Flow real."""
    script = REPO / "tools" / "fase3_aceptacion.py"
    assert script.is_file()
    src = script.read_text(encoding="utf-8")
    assert "NOT_DEMONSTRATED" in src, (
        "el protocolo debe declarar honestamente que no se ha ejecutado")
    assert CRITERIOS["min_videos"] == 10 and CRITERIOS["nichos"] == 2


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
