# -*- coding: utf-8 -*-
"""PASO 2 · Tests del validador editorial de la Fase E (minidramas).

Herméticos por diseño: el módulo bajo prueba es Python puro (sin red,
sin Flow, sin I/O). Estos tests además pasan con la guardia de red del
conftest activa (cero DNS, cero internet).

Contrato probado (spec § Fase E):
  - campos obligatorios reutilizando nombres del Production JSON
    (video_prompt, duration_target, initial_state, final_state,
    casting, story_function) — sin nombres duplicados alternativos;
  - un solo párrafo en video_prompt;
  - nombres de personaje en MAYÚSCULAS (casting y prompt);
  - máximo 12 palabras habladas con conteo DETERMINISTA y devolución
    del TEXTO que excede el límite;
  - estado final presente;
  - duración objetivo configurable (exacta);
  - episodio: 6 clips (configurable), clip_id únicos, episode_id
    coherente.

Ejecutar: python3 -m pytest tests/test_minidrama_clip_validator.py -q
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.minidrama_clip_validator import (  # noqa: E402
    CAMPOS_OBLIGATORIOS,
    contar_palabras_habladas,
    extraer_dialogo,
    validar_clip,
    validar_episodio,
)


def clip_bueno(**overrides):
    """Ficha de clip válida según la Fase E (formato vertical del contrato)."""
    base = {
        "episode_id": "EP01",
        "clip_id": "C01",
        "start_ms": 0,
        "end_ms": 10000,
        "duration_target": 10.0,
        "story_function": "Hook visual del incidente inducido",
        "location": "cocina de la vecindad",
        "time_of_day": "noche",
        "visual_style": "drama urbano, luz cálida",
        "camera": "plano medio, ligero dolly-in",
        "lighting": "prácticos de cocina",
        "casting": ["MARÍA", "JORGE"],
        "initial_state": "MARÍA apila platos sucios junto al fregadero",
        "action": "JORGE entra mojado y deja un sobre sobre la mesa",
        "change": "el sobre queda abierto a la vista de MARÍA",
        "final_state": "MARÍA sostiene el sobre abierto a los 9.9 s, "
                       "JORGE aún de espaldas",
        "image_prompt": "cocina vecindad nocturna, tensión doméstica",
        "video_prompt": (
            'Cocina nocturna de vecindad. MARÍA apila platos sucios con '
            'gesto contenido. JORGE entra empapado y deja un sobre sobre '
            'la mesa sin mirarla: "Esto no puede seguir así". MARÍA lo '
            'abre y su respiración se corta. Al segundo 9.9 sostiene el '
            'sobre abierto mientras JORGE sigue de espaldas.'),
        "references": ["ref_maria.png", "ref_jorge.png"],
        "audio": {"dialogue_speaker": "JORGE", "sfx": "lluvia"},
    }
    base.update(overrides)
    return base


# ── casos buenos ──────────────────────────────────────────────────────

def test_clip_bueno_pasa_completo():
    r = validar_clip(clip_bueno())
    assert r["ok"], r["fallos"]
    assert r["fallos"] == []
    assert r["palabras_habladas"] == 5  # "Esto no puede seguir así"
    assert r["exceso"] is None


def test_campos_obligatorios_reutilizan_nombres_del_production_json():
    """Los nombres exigidos son EXACTAMENTE los del Production JSON / ficha
    Fase E; ningún alias nuevo."""
    assert CAMPOS_OBLIGATORIOS == (
        "video_prompt", "duration_target", "initial_state",
        "final_state", "casting", "story_function")


def test_limite_de_palabras_es_configurable_y_se_cumple():
    c = clip_bueno(video_prompt='MARÍA grita: "basta ya"', casting=["MARÍA"])
    assert validar_clip(c, max_palabras=3)["ok"]     # 2 palabras habladas
    assert validar_clip(c, max_palabras=1)["ok"] is False


def test_episodio_bueno_de_seis_clips_pasa():
    clips = [clip_bueno(clip_id=f"C0{i + 1}") for i in range(6)]
    r = validar_episodio(clips)
    assert r["ok"], (r["fallos_episodio"],
                     [c["fallos"] for c in r["clips"] if not c["ok"]])
    assert r["n_clips"] == 6


# ── campos obligatorios ───────────────────────────────────────────────

@pytest.mark.parametrize("campo", CAMPOS_OBLIGATORIOS)
def test_cada_campo_obligatorio_ausente_falla(campo):
    ficha = clip_bueno()
    ficha.pop(campo)
    r = validar_clip(ficha)
    assert not r["ok"]
    assert any(f["campo"] == campo and f["regla"] == "CAMPO_OBLIGATORIO"
               for f in r["fallos"])


def test_campo_vacio_cuenta_como_ausente():
    r = validar_clip(clip_bueno(initial_state="   ", casting=[]))
    assert not r["ok"]
    campos = {f["campo"] for f in r["fallos"] if f["regla"] == "CAMPO_OBLIGATORIO"}
    assert {"initial_state", "casting"} <= campos


# ── un solo párrafo ───────────────────────────────────────────────────

def test_video_prompt_con_saltos_de_linea_falla():
    r = validar_clip(clip_bueno(video_prompt="Cocina nocturna.\nMARÍA espera."))
    assert not r["ok"]
    assert any(f["regla"] == "PARRAFO_UNICO" for f in r["fallos"])


# ── nombres en MAYÚSCULAS ─────────────────────────────────────────────

def test_casting_en_minusculas_falla():
    r = validar_clip(clip_bueno(casting=["maría"]))
    assert not r["ok"]
    assert any(f["regla"] == "NOMBRE_MAYUSCULAS" and f["campo"] == "casting"
               for f in r["fallos"])


def test_nombre_en_minusculas_dentro_del_prompt_falla():
    r = validar_clip(clip_bueno(
        video_prompt='Cocina nocturna. maría apila platos. JORGE llega: '
                     '"Esto no puede seguir así". MARÍA abre el sobre.'))
    assert not r["ok"]
    assert any(f["regla"] == "NOMBRE_MAYUSCULAS" and f["campo"] == "video_prompt"
               for f in r["fallos"])


def test_personaje_del_casting_ausente_en_prompt_falla():
    r = validar_clip(clip_bueno(casting=["MARÍA", "JORGE", "LUZ"]))
    assert not r["ok"]
    assert any(f["regla"] == "NOMBRE_AUSENTE" and "LUZ" in f["detalle"]
               for f in r["fallos"])


# ── conteo determinista de palabras habladas ─────────────────────────

def test_solo_cuentan_los_fragmentos_entre_comillas():
    # la descripción visual tiene muchas palabras; el diálogo 5
    prompt = ('Cocina nocturna de vecindad con luz cálida y platos apilados '
              'junto a la ventana. JORGE llega: "no puedo seguir"')
    assert extraer_dialogo(prompt) == ["no puedo seguir"]
    assert contar_palabras_habladas(prompt) == 3


def test_numero_en_cifra_cuenta_uno_y_en_letras_cuenta_sus_tokens():
    assert contar_palabras_habladas('"vuelvo en 2026"') == 3       # vuelvo,en,2026
    assert contar_palabras_habladas('"vuelvo en dos mil"') == 4    # vuelvo,en,dos,mil


def test_compuesto_con_guion_cuenta_dos_y_raya_de_dialogo_no_suma():
    assert contar_palabras_habladas('"es algo-bueno"') == 3         # es,algo,bueno
    assert contar_palabras_habladas('JORGE dice: —"hola"') == 1


def test_comillas_curvas_y_angulares_cuentan_igual():
    assert contar_palabras_habladas('MARÍA: “basta ya”') == 2
    assert contar_palabras_habladas('MARÍA: «basta ya»') == 2


def test_exceso_devuelve_el_texto_que_excede_el_limite():
    c = clip_bueno(video_prompt='JORGE: "no puedo seguir así contigo esta noche"',
                   casting=["JORGE"])
    r = validar_clip(c, max_palabras=4)  # 7 palabras habladas
    assert not r["ok"]
    assert r["palabras_habladas"] == 7
    assert r["exceso"] == "contigo esta noche"  # palabras 5..7


def test_exceso_es_none_si_no_excede():
    r = validar_clip(clip_bueno())
    assert r["exceso"] is None


# ── estado final y duración ───────────────────────────────────────────

def test_estado_final_vacio_falla():
    r = validar_clip(clip_bueno(final_state="  "))
    assert not r["ok"]
    assert any(f["campo"] == "final_state" for f in r["fallos"])


def test_duracion_distinta_del_objetivo_falla():
    r = validar_clip(clip_bueno(duration_target=8.0))
    assert not r["ok"]
    assert any(f["regla"] == "DURACION_OBJETIVO" for f in r["fallos"])


def test_duracion_objetivo_es_configurable():
    c = clip_bueno(duration_target=8.0)
    r = validar_clip(c, duracion_objetivo=8.0)
    assert r["ok"], r["fallos"]


def test_duracion_no_numerica_falla():
    r = validar_clip(clip_bueno(duration_target="diez"))
    assert not r["ok"]
    assert any(f["regla"] == "DURACION_NUMERICA" for f in r["fallos"])


# ── episodio ──────────────────────────────────────────────────────────

def test_episodio_con_menos_de_seis_clips_falla():
    clips = [clip_bueno(clip_id=f"C0{i + 1}") for i in range(5)]
    r = validar_episodio(clips)
    assert not r["ok"]
    assert any(f["regla"] == "NUM_CLIPS" for f in r["fallos_episodio"])


def test_episodio_num_clips_configurable():
    clips = [clip_bueno(clip_id=f"C0{i + 1}", duration_target=8.0)
             for i in range(6)]
    r = validar_episodio(clips, duracion_objetivo=8.0)
    assert r["ok"], (r["fallos_episodio"],
                     [c["fallos"] for c in r["clips"] if not c["ok"]])


def test_episodio_clip_ids_duplicados_fallan():
    clips = [clip_bueno(clip_id="C01") for _ in range(6)]
    r = validar_episodio(clips)
    assert not r["ok"]
    assert any(f["regla"] == "CLIP_ID_UNICOS" for f in r["fallos_episodio"])


def test_episodio_con_episode_id_incoherente_falla():
    clips = [clip_bueno(clip_id=f"C0{i + 1}", episode_id=("EP01" if i < 3
                                                          else "EP02"))
             for i in range(6)]
    r = validar_episodio(clips)
    assert not r["ok"]
    assert any(f["regla"] == "EPISODE_ID_COHERENTE"
               for f in r["fallos_episodio"])


def test_episodio_propaga_el_fallo_del_clip_malo():
    clips = [clip_bueno(clip_id=f"C0{i + 1}") for i in range(6)]
    clips[3]["duration_target"] = 8.0
    r = validar_episodio(clips)
    assert not r["ok"]
    assert r["clips"][3]["ok"] is False
    assert all(c["ok"] for i, c in enumerate(r["clips"]) if i != 3)


def test_episodio_vacio_falla_con_regla_propia():
    r = validar_episodio([])
    assert not r["ok"]
    assert any(f["regla"] == "EPISODIO_CON_CLIPS" for f in r["fallos_episodio"])


# ── 0.1 · diálogo estructurado y heurística sin comillas ─────────────

def _raya_de(n: int) -> str:
    return "—" + " ".join(f"palabra{i}" for i in range(1, n + 1)) + "—"


def test_raya_con_20_palabras_falla_antes_valido():
    """Caso de regresión 0.1: 20 palabras entre rayas tras un verbo de
    habla pasaban como válidos (REGLA DE LA RAYA: tras «grita:» cuenta)."""
    r = validar_clip(clip_bueno(
        video_prompt=f"MARÍA grita: {_raya_de(20)}",
        casting=["MARÍA"]))
    assert not r["ok"]
    assert r["palabras_habladas"] == 20
    assert any(f["regla"] == "MAX_PALABRAS_HABLADAS" for f in r["fallos"])
    assert r["exceso"] == "palabra13 " + " ".join(
        f"palabra{i}" for i in range(14, 21))


def test_verbo_habla_14_palabras_falla_antes_valido():
    """Caso de regresión 0.1: 14 palabras tras 'dice:' pasaban como válidos."""
    catorce = " ".join(f"v{i}" for i in range(1, 15))
    r = validar_clip(clip_bueno(video_prompt=f"JORGE dice: {catorce}",
                                casting=["JORGE"]))
    assert not r["ok"]
    assert r["palabras_habladas"] == 14
    assert r["exceso"] == "v13 v14"


def test_habla_fuera_de_comillas_genera_aviso_sin_romper_ok():
    r = validar_clip(clip_bueno(
        video_prompt="MARÍA limpia la cocina y dice: —no puedo más— y sale.",
        casting=["MARÍA"]))
    assert r["ok"], r["fallos"]          # 3 palabras: no excede
    assert any(a["regla"] == "DIALOGO_SIN_COMILLAS" for a in r["avisos"])
    assert r["fuente_conteo"] == "video_prompt"


def test_verbo_habla_con_comillas_no_duplica_conteo():
    r = validar_clip(clip_bueno(
        video_prompt='MARÍA dice: "hola que tal" y se va.', casting=["MARÍA"]))
    assert r["ok"], r["fallos"]
    assert r["palabras_habladas"] == 3   # no 6
    assert not any(a["regla"] == "DIALOGO_SIN_COMILLAS" for a in r["avisos"])


def test_dialogue_estructurado_es_fuente_de_verdad():
    """(a) El campo `dialogue` manda: el prompt no se escanea."""
    doce = " ".join(f"p{i}" for i in range(1, 13))
    r = validar_clip(clip_bueno(
        video_prompt=f"Cocina nocturna con MARÍA. {_raya_de(20)}",
        casting=["MARÍA"], dialogue=[{"personaje": "MARÍA", "texto": doce}]))
    assert r["ok"], (r["fallos"], r["avisos"])
    assert r["palabras_habladas"] == 12
    assert r["fuente_conteo"] == "dialogue"
    assert not r["avisos"]               # no hay heurística → sin avisos


def test_dialogue_estructurado_con_exceso_falla_y_devuelve_exceso():
    catorce = " ".join(f"p{i}" for i in range(1, 15))
    r = validar_clip(clip_bueno(dialogue=[
        {"personaje": "MARÍA", "texto": catorce}]))
    assert not r["ok"]
    assert any(f["campo"] == "dialogue" and
               f["regla"] == "MAX_PALABRAS_HABLADAS" for f in r["fallos"])
    assert r["exceso"] == "p13 p14"


def test_dialogue_vacio_significa_sin_dialogo():
    r = validar_clip(clip_bueno(dialogue=[]))
    assert r["palabras_habladas"] == 0
    assert r["fuente_conteo"] == "dialogue"


def test_dialogue_malformado_cae_a_heuristica_con_aviso():
    veinte = " ".join(f"p{i}" for i in range(1, 21))
    r = validar_clip(clip_bueno(video_prompt=f"MARÍA grita: —{veinte}—",
                                casting=["MARÍA"],
                                dialogue=[{"sin": "texto"}, 42]))
    assert not r["ok"]
    assert any(a["regla"] == "DIALOGUE_MALFORMADO" for a in r["avisos"])
    assert r["palabras_habladas"] == 20  # heurística del prompt
    assert r["fuente_conteo"] == "video_prompt"


def test_dialogue_personaje_en_minusculas_falla():
    r = validar_clip(clip_bueno(dialogue=[{"personaje": "jorge",
                                           "texto": "hola"}]))
    assert not r["ok"]
    assert any(f["campo"] == "dialogue" and
               f["regla"] == "NOMBRE_MAYUSCULAS" for f in r["fallos"])


def test_prompt_sin_habla_no_genera_avisos():
    r = validar_clip(clip_bueno())
    assert r["ok"] and r["avisos"] == []
    assert r["palabras_habladas"] == 5   # la cita del clip_bueno sigue contando


# ── R6 · REGLA DE LA RAYA: acotación narrativa NO es diálogo ─────────

def test_raya_acotacion_narrativa_no_cuenta():
    """Caso R6 (falso positivo corregido): un par de rayas como acotación
    dentro de una frase narrativa NO cuenta como palabras habladas."""
    r = validar_clip(clip_bueno(
        video_prompt="El sol —que ya caía— quemaba el huerto y MARÍA "
                     "corrió a cubrirse.",
        casting=["MARÍA"]))
    assert r["ok"], r["fallos"]
    assert r["palabras_habladas"] == 0
    assert r["avisos"] == []             # sin DIALOGO_SIN_COMILLAS
    assert r["fuente_conteo"] == "ninguna"


def test_raya_tras_punto_y_seguido_no_cuenta():
    """Raya tras una oración narrativa (punto y seguido) NO abre diálogo."""
    r = validar_clip(clip_bueno(
        video_prompt="MARÍA entró. —con calma— miró la mesa y respiró.",
        casting=["MARÍA"]))
    assert r["ok"], r["fallos"]
    assert r["palabras_habladas"] == 0
    assert r["avisos"] == []


def test_raya_tras_verbo_de_habla_cuenta():
    """Raya tras verbo de habla (sin «:») SÍ abre diálogo."""
    r = validar_clip(clip_bueno(
        video_prompt="MARÍA se detiene y grita —¡salid de ahí!— al aire "
                     "libre del huerto.",
        casting=["MARÍA"]))
    assert r["ok"], r["fallos"]          # 3 palabras: no excede
    assert r["palabras_habladas"] == 3
    assert "¡salid de ahí!" in r["dialogo"]
    assert any(a["regla"] == "DIALOGO_SIN_COMILLAS" for a in r["avisos"])


def test_raya_tras_dos_puntos_cuenta():
    """Raya tras «:» (sin verbo de habla delante) SÍ abre diálogo."""
    r = validar_clip(clip_bueno(
        video_prompt="El chef sirvió el plato: —por fin— y MARÍA sonrió.",
        casting=["MARÍA"]))
    assert r["ok"], r["fallos"]
    assert r["palabras_habladas"] == 2
    assert "por fin" in r["dialogo"]
    assert any(a["regla"] == "DIALOGO_SIN_COMILLAS" for a in r["avisos"])


def test_raya_al_inicio_de_linea_cuenta():
    """Raya al inicio de línea (o del texto) SÍ abre diálogo."""
    from services.minidrama_clip_validator import _fragmentos_heuristicos
    frags, fuera = _fragmentos_heuristicos(
        "Plano del huerto al atardecer.\n—Volví— dice MARÍA.")
    assert frags == ["Volví"]
    assert fuera == 1


# ── Q5 · HABLA_SIN_COMILLAS_POSIBLE (verbo fuera de la lista cerrada) ──

_LARGAS = ("uno dos tres cuatro cinco seis siete ocho nueve diez "
           "once doce trece catorce")


def test_ladra_con_14_palabras_genera_aviso():
    """«ladra:» no está en la lista cerrada → la heurística no lo cuenta,
    pero con texto tras «:» por encima del límite YA no pasa en silencio:
    aviso HABLA_SIN_COMILLAS_POSIBLE (sin afectar `ok`)."""
    c = clip_bueno(video_prompt=(
        f"Cocina nocturna. JORGE sirve agua. EL PERRO ladra: {_LARGAS}. "
        "MARÍA cubre su oreja."))
    r = validar_clip(c)
    assert r["ok"], r["fallos"]          # el aviso no es un fallo
    assert any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
               for a in r["avisos"]), r["avisos"]
    assert "ladra" in next(a["detalle"] for a in r["avisos"]
                           if a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE")
    assert r["palabras_habladas"] == 0   # la heurística NO lo cuenta


def test_acotacion_normal_no_avisa():
    """Acotación narrativa (sin «verbo:» largo) NO genera el aviso Q5."""
    c = clip_bueno(video_prompt=(
        "Cocina nocturna. JORGE trae el sobre y MARÍA lo abre; el sol "
        "—que ya caía— quemaba el camino y la cena se enfría mientras "
        "los dos miran la mesa."))
    r = validar_clip(c)
    assert r["ok"], r["fallos"]
    assert not any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
                   for a in r["avisos"])


def test_habla_corta_con_verbo_desconocido_no_avisa():
    """«ladra:» con texto corto (≤ límite) no avisa — solo el exceso."""
    c = clip_bueno(video_prompt=(
        "Cocina nocturna. JORGE duda y MARÍA imita al perro ladra: "
        "guau guau. Los dos ríen."))
    r = validar_clip(c)
    assert r["ok"], r["fallos"]
    assert not any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
                   for a in r["avisos"])


def test_verbo_cerrado_largo_no_duplica_el_aviso():
    """«grita:» + 14 palabras: la heurística YA lo cuenta (MAX_PALABRAS_
    HABLADAS + DIALOGO_SIN_COMILLAS) — el aviso Q5 NO se duplica."""
    c = clip_bueno(video_prompt=(
        f"Cocina nocturna. JORGE se levanta de golpe y MARÍA grita: "
        f"{_LARGAS}. JORGE baja la vista."))
    r = validar_clip(c)
    assert r["ok"] is False               # 14 > 12 → fallo MAX
    assert any(f["regla"] == "MAX_PALABRAS_HABLADAS" for f in r["fallos"])
    assert any(a["regla"] == "DIALOGO_SIN_COMILLAS" for a in r["avisos"])
    assert not any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
                   for a in r["avisos"])


def test_con_dialogue_estructurado_el_prompt_no_se_escanea():
    """Fuente de verdad: `dialogue` (Q5, documentado). El «ladra:» del
    prompt ni cuenta ni avisa — con `dialogue` presente el prompt no se
    escanea; queda anotada la recomendación de hacerlo obligatorio."""
    c = clip_bueno(
        video_prompt=(f"Cocina nocturna. JORGE espera. EL PERRO ladra: "
                      f"{_LARGAS}. MARÍA tapa la olla."),
        dialogue=[{"personaje": "MARÍA", "texto": "basta ya"}])
    r = validar_clip(c)
    assert r["fuente_conteo"] == "dialogue"
    assert r["palabras_habladas"] == 2
    assert not any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
                   for a in r["avisos"])


def test_no_duplica_lo_ya_contado_por_comillas_o_rayas():
    """El escaneo Q5 corre sobre comillas y rayas YA blankadas: lo contado
    por otras vías no vuelve a avisar (nunca se duplica)."""
    c = clip_bueno(video_prompt=(
        "Cocina. JORGE entra y MARÍA dice: \"hasta aquí llegamos y no "
        "hay más que hablar hoy\" —el sobre— sin mirar a los ojos."))
    r = validar_clip(c)
    assert not any(a["regla"] == "HABLA_SIN_COMILLAS_POSIBLE"
                   for a in r["avisos"]), r["avisos"]


# ── robustez ──────────────────────────────────────────────────────────

def test_entrada_que_no_es_dict_no_explota():
    r = validar_clip("no soy una ficha")
    assert r["ok"] is False
    assert r["fallos"][0]["regla"] == "TIPO"


def test_validador_es_puro_no_abre_sockets(tmp_path):
    """Rebanada honesta: el módulo no importa nada de red. Si alguien añade
    una dependencia de red/Flow a este validador, este test lo delata."""
    import services.minidrama_clip_validator as mod
    import inspect
    fuente = inspect.getsource(mod)
    for prohibido in ("import socket", "import requests", "import httpx",
                      "import urllib", "flow_jobs", "mcp_manager"):
        assert prohibido not in fuente, f"el validador debe seguir puro: {prohibido}"


if __name__ == "__main__":
    # Batería standalone (tests/run_all.py): imprime el resumen "N OK ·
    # M fallos" que el runner parsea, contado con un plugin de pytest.
    import pytest as _pytest

    class _Resumen:
        def __init__(self) -> None:
            self.ok = self.fallos = 0

        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                if report.passed:
                    self.ok += 1
                elif report.failed:
                    self.fallos += 1

    _res = _Resumen()
    _code = _pytest.main([__file__, "-q"], plugins=[_res])
    print(f"\n{_res.ok} OK · {_res.fallos} fallos")
    sys.exit(int(_code))
