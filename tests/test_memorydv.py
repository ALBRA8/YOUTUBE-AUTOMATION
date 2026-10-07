#!/usr/bin/env python3
"""MemoryDV — batería de memoria (storage/retrieval/consolidation/isolation).

Cubre: alta de memorias con los 18 campos del contrato y dominio forzado
(§8), query con filtros + utilidad persistida, tolerancia a líneas
corruptas, consolidación §9 (observaciones → candidato, idempotente),
validación de candidatos (inválido / sin regresión / con regresión real
bajo tests/), decaimiento con retiro, aislamiento del sandbox y shape de
stats().

Uso:  cd yt_automation_v2 && python3 tests/test_memorydv.py
"""
import json, sys, tempfile
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
_TMP = Path(tempfile.mkdtemp(prefix="memorydv_test_"))
from services import memorydv as mem  # noqa: E402
mem.MEMORY_DIR = _TMP / "memorydv"   # hermético: nunca toca data/ real

OK, FAIL = 0, 0
def check(nombre, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print(f"  ✓ {nombre}")
    else: FAIL += 1; print(f"  ✗ {nombre} {extra}")

# Campos universales del contrato (§8): presentes en TODA memoria.
CAMPOS = {"memory_id", "agent_id", "domain", "type", "content", "source",
          "evidence", "provenance", "confidence", "truth_level", "created_at",
          "updated_at", "last_verified", "relevance", "utility", "decay",
          "scope", "status"}


def _raw(nombre: str) -> list:
    """Lee un JSONL del sandbox devolviendo solo las líneas JSON válidas."""
    ruta = Path(mem.MEMORY_DIR) / nombre
    if not ruta.exists():
        return []
    out = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            out.append(json.loads(linea))
        except ValueError:
            pass
    return out


def _por_id(nombre: str) -> dict:
    return {d["memory_id"]: d for d in _raw(nombre)}


def main() -> int:
    print("── 1. alta de memorias: 18 campos del contrato y dominio forzado (§8)")
    ep1 = mem.record_episode("Pipeline ejecutó TTS para la producción p1",
                             source="pipeline._run",
                             extra={"production_id": "p1", "step": "tts",
                                    "result": "ok"})
    ep2 = mem.record_episode("Export Flow terminó para la ejecución e9",
                             source="pipeline.flow_export",
                             extra={"domain": "agente_externo",
                                    "execution_id": "e9"})
    obs1 = mem.record_observation(
        "Whisper devuelve segmentos vacíos cuando el audio empieza con silencio",
        source="mcp")
    fact1 = mem.record_fact("Flow solo exporta MP4 con H.264 en colas < 100 jobs",
                            source="manual")
    check("episodio: los 18 campos del contrato presentes",
          all(c in ep1 for c in CAMPOS), str(sorted(CAMPOS - set(ep1))))
    check("dominio forzado a youtube_automation aunque el llamador intente otro",
          ep1["domain"] == "youtube_automation"
          and ep2["domain"] == "youtube_automation"
          and ep2.get("execution_id") == "e9")
    check("defaults: observación provenance='observed'·conf 0.6 · hecho FACTUAL·system",
          obs1["provenance"] == "observed"
          and abs(obs1["confidence"] - 0.6) < 1e-9
          and obs1["type"] == "EPISODIC"
          and fact1["type"] == "FACTUAL" and fact1["scope"] == "system")
    ids = {ep1["memory_id"], ep2["memory_id"], obs1["memory_id"],
           fact1["memory_id"]}
    check("memory_id únicos (hex de 16) entre registros",
          len(ids) == 4 and all(len(i) == 16 for i in ids))
    check("extra fusiona producción/step sin tocar campos nucleares",
          ep1.get("production_id") == "p1" and ep1.get("step") == "tts"
          and ep1["type"] == "EPISODIC" and len(ep1["memory_id"]) == 16)

    print("── 2. query: tipo, scope, texto, límite/orden y utilidad persistida")
    fact2 = mem.record_fact("Gemini 2.5 Flash genera guion JSON válido",
                            source="mcp", scope="qa")
    obs2 = mem.record_observation(
        "Fal.ai timeout 504 cuando la cola supera 20 jobs",
        source="mcp", scope="provider")
    q_ep = mem.query(mem_type="EPISODIC")
    check("query por tipo devuelve solo EPISODIC (2 episodios + 2 observaciones)",
          len(q_ep) == 4 and all(r["type"] == "EPISODIC" for r in q_ep),
          f"len={len(q_ep)}")
    q_prov = mem.query(scope="provider")
    check("query por scope filtra provider (Whisper + Fal)",
          len(q_prov) == 2 and all(r["scope"] == "provider" for r in q_prov),
          f"len={len(q_prov)}")
    q_txt = mem.query(text="gemini")
    check("query por texto (case-insensitive) encuentra el hecho de Gemini",
          len(q_txt) == 1 and "gemini" in q_txt[0]["content"].casefold())
    q_all = mem.query(mem_type="EPISODIC")
    q_lim = mem.query(mem_type="EPISODIC", limit=1)
    check("límite respetado y orden por relevancia (desempate utilidad): 1º == top",
          len(q_lim) == 1
          and q_lim[0]["memory_id"] == q_all[0]["memory_id"])
    mem.query(text="flow solo exporta")
    hechos = _por_id("factual.jsonl")
    check("utilidad incrementada y persistida en el JSONL (recupero → uso)",
          hechos[fact1["memory_id"]]["utility"] >= 1.0
          and hechos[fact2["memory_id"]]["utility"] >= 1.0,
          str({k: v["utility"] for k, v in hechos.items()}))

    print("── 3. tolerancia: línea corrupta jamás tumba la consulta")
    with open(Path(mem.MEMORY_DIR) / "episodic.jsonl", "a",
              encoding="utf-8") as fh:
        fh.write('{"memory_id": "roto", sin_cerrar: \n')
    q = mem.query(mem_type="EPISODIC")
    check("línea corrupta tolerada: query sigue funcionando y stats la cuenta",
          len(q) == 4 and mem.stats()["corrupted_lines"] >= 1,
          f"len={len(q)} corruptas={mem.stats()['corrupted_lines']}")
    check("la línea corrupta sobrevive verbatim a la reescritura por utilidad",
          "sin_cerrar" in (Path(mem.MEMORY_DIR)
                           / "episodic.jsonl").read_text(encoding="utf-8")
          and mem.stats()["corrupted_lines"] >= 1)

    print("── 4. consolidación §9: observaciones repetidas → candidato")
    CAUSA = ("Google Flow falla con 429 cuando la cola supera N jobs "
             "concurrentes y el export se cuelga sin dejar trazas")
    for i in range(4):
        mem.record_observation(f"{CAUSA} [caso {i}]", source="mcp",
                               scope="provider", confidence=0.8)
    res = mem.consolidate(min_pattern=3)
    activo1 = next((c for c in mem.candidates()
                    if c.get("status") == "candidate"), None)
    check("consolidación crea exactamente 1 candidato con kind válido",
          len(res["candidates_created"]) == 1 and activo1 is not None
          and activo1["kind"] in ("SKILL_CANDIDATE", "SEMANTIC_CANDIDATE"),
          str(res))
    occ1 = activo1["occurrences"]
    check("occurrences agrupa las 4 observaciones (>= 3) con evidencia agregada",
          len(occ1) >= 3 and isinstance(activo1["evidence"], list)
          and activo1["mean_confidence"] >= 0.75)
    episodios = _por_id("episodic.jsonl")
    check("observaciones fuente marcadas status='candidate' (no se borran)",
          all(episodios[i]["status"] == "candidate" for i in occ1))
    res2 = mem.consolidate(min_pattern=3)
    check("segunda consolidación idempotente (0 nuevos) y candidates_active == 1",
          res2["candidates_created"] == []
          and mem.stats()["candidates_active"] == 1)

    print("── 5. consolidación bajo umbral: causas distintas no candidatizan")
    mem.record_observation("ElevenLabs rechaza guiones con más de 5000 "
                           "caracteres en el campo narration",
                           source="mcp", scope="provider", confidence=0.5)
    mem.record_observation("ElevenLabs duplica espacios cuando el guion llega "
                           "con saltos de línea dobles",
                           source="mcp", scope="provider", confidence=0.5)
    res3 = mem.consolidate()
    check("causas distintas bajo umbral → 0 candidatos y activos siguen == 1",
          res3["candidates_created"] == []
          and mem.stats()["candidates_active"] == 1)

    print("── 6. validate_candidate inválido: retiro sin promoción")
    cid1 = activo1["candidate_id"]
    r_inv = mem.validate_candidate(cid1, "invalid")
    c1 = next(c for c in _raw("candidates.jsonl")
              if c.get("candidate_id") == cid1)
    sin_promo = mem.query(mem_type="SEMANTIC") + mem.query(mem_type="PROCEDURAL")
    check("veredicto inválido → candidato retired y sin promoción creada",
          r_inv.get("ok") is True and c1["status"] == "retired"
          and sin_promo == [], str(r_inv))
    episodios = _por_id("episodic.jsonl")
    check("observaciones fuente vuelven a status='active' (observación no promovida)",
          all(episodios[i]["status"] == "active" for i in occ1))

    print("── 7. validate_candidate válido SIN regresión → ValueError (§11)")
    res4 = mem.consolidate()
    activo2 = next((c for c in mem.candidates()
                    if c.get("status") == "candidate"), None)
    cid2 = activo2["candidate_id"]
    msg_err = ""
    try:
        mem.validate_candidate(cid2, "valid")
    except ValueError as e:
        msg_err = str(e)
    check("re-consolidación tras inválido recrea 1 candidato; "
          "valid sin regresión → ValueError citando 'regresión'",
          len(res4["candidates_created"]) == 1 and "regresión" in msg_err.lower(),
          f"creados={res4['candidates_created']} err={msg_err[:60]}")
    c2 = next(c for c in _raw("candidates.jsonl")
              if c.get("candidate_id") == cid2)
    check("el candidato no se toca tras el ValueError (sigue 'candidate')",
          c2["status"] == "candidate")

    print("── 8. validate_candidate válido CON regresión real → promoción")
    r2 = mem.validate_candidate(cid2, "valid", verified_by="qa_humano",
                                regression_test="tests/test_qa_forensics.py")
    check("valid con regresión → promoted_to devuelto",
          r2.get("ok") is True and bool(r2.get("promoted_to")), str(r2)[:120])
    m = r2.get("promoted") or {}
    promovida_en_disco = any(
        d.get("memory_id") == r2.get("promoted_to")
        for d in _raw("semantic.jsonl") + _raw("procedural.jsonl"))
    check("memoria promovida persistida: provenance promoted, truth_level "
          "verified, confianza 0.9, tipo SEMANTIC/PROCEDURAL",
          promovida_en_disco and m.get("provenance") == "promoted"
          and m.get("truth_level") == "verified"
          and abs(m.get("confidence", 0) - 0.9) < 1e-9
          and m.get("type") in ("SEMANTIC", "PROCEDURAL"))
    check("evidencia de la promovida incluye el ref del regression_test",
          any(ev.get("kind") == "regression_test"
              and "test_qa_forensics.py" in str(ev.get("ref"))
              for ev in m.get("evidence", [])))
    c2 = next(c for c in _raw("candidates.jsonl")
              if c.get("candidate_id") == cid2)
    check("candidato retired con promoted_to == memory_id de la promovida",
          c2["status"] == "retired"
          and c2.get("promoted_to") == r2["promoted_to"])
    episodios = _por_id("episodic.jsonl")
    check("observaciones fuente quedan active con truth_level='pattern'",
          all(episodios[i]["status"] == "active"
              and episodios[i]["truth_level"] == "pattern" for i in occ1))
    check("needs_human_approval: False con regresión · True sin ella (§11)",
          mem.needs_human_approval(m) is False
          and mem.needs_human_approval({**m, "evidence": []}) is True)

    print("── 9. regresión inválida: inexistente o fuera de tests/ → ValueError")
    CAUSA3 = ("Sanitizer corta los emojis del guion cuando el TTS los "
              "pronuncia mal y rompe el ritmo de la narración")
    for i in range(3):
        mem.record_observation(f"{CAUSA3} [caso {i}]", source="mcp",
                               scope="production", confidence=0.9)
    mem.consolidate()
    activo3 = next((c for c in mem.candidates()
                    if c.get("status") == "candidate"), None)
    cid3 = activo3["candidate_id"]
    errores = 0
    try:
        mem.validate_candidate(cid3, "valid",
                               regression_test="tests/test_regresion_fantasma.py")
    except ValueError:
        errores += 1
    try:
        mem.validate_candidate(cid3, "valid",
                               regression_test="backend/services/memorydv.py")
    except ValueError:
        errores += 1
    check("regresión inexistente o fuera de tests/ → ValueError en ambos casos",
          errores == 2, f"errores={errores}")
    c3 = next(c for c in _raw("candidates.jsonl")
              if c.get("candidate_id") == cid3)
    check("el candidato sobrevive a los fallos de ruta (sigue 'candidate')",
          c3["status"] == "candidate")

    print("── 10. apply_decay: relevancia débil → retiro")
    obsX = mem.record_observation("Voz ElevenLabs con velocidad 1.05 suena "
                                  "natural en el nicho de misterio",
                                  source="mcp", scope="provider")
    n1 = mem.apply_decay(factor=0.2)
    rawX = _por_id("episodic.jsonl")[obsX["memory_id"]]
    n2 = mem.apply_decay(factor=0.2)
    rawX2 = _por_id("episodic.jsonl")[obsX["memory_id"]]
    check("apply_decay(factor=0.2): 1ª pasada 0 retirados y relevancia 0.2; "
          "2ª retira y devuelve el conteo (>= 1)",
          n1 == 0 and abs(rawX["relevance"] - 0.2) < 1e-6 and n2 >= 1,
          f"n1={n1} n2={n2} rel={rawX['relevance']}")
    check("la observación con relevance < 0.05 queda retired",
          rawX2["status"] == "retired" and rawX2["relevance"] < 0.05,
          str(rawX2["relevance"]))
    obsY = mem.record_observation("Nicho misterio rinde mejor con voz pausada "
                                  "y pausas de 400 ms", source="mcp")
    n3 = mem.apply_decay()
    rawY = _por_id("episodic.jsonl")[obsY["memory_id"]]
    check("decay por defecto usa el decay del propio registro (0.98, no retira)",
          n3 == 0 and abs(rawY["relevance"] - 0.98) < 1e-6,
          f"n3={n3} rel={rawY['relevance']}")

    print("── 11. aislamiento §8: el sandbox es el único storage tocado")
    nombres = sorted(p.name for p in mem.MEMORY_DIR.iterdir())
    esperados = {"candidates.jsonl", "episodic.jsonl", "factual.jsonl",
                 "procedural.jsonl", "semantic.jsonl"}
    nucleo = {"episodic.jsonl", "factual.jsonl", "semantic.jsonl",
              "candidates.jsonl"}
    check("sandbox hermético: solo JSONL de memorydv bajo MEMORY_DIR parcheado "
          "(creación perezosa, 0 ficheros extraños)",
          set(nombres) <= esperados and nucleo <= set(nombres)
          and str(mem.MEMORY_DIR.resolve()).startswith(str(_TMP)),
          str(nombres))
    # v2.19 · NOTA: los ganchos de producción (orchestrator/flow_jobs) escriben
    # por diseño en backend/data/memorydv (gitignored) cuando corren SIN
    # parche — este battery parchea, así que sus registros van al sandbox:
    # se comprueba que TODO registro de ESTA batería vive bajo _TMP.
    st_iso = mem.stats()
    check("todos los registros de la batería viven bajo el sandbox",
          str(st_iso.get("dir", "")).startswith(str(_TMP.resolve()))
          or str(st_iso.get("dir", "")).startswith(str(_TMP)), st_iso.get("dir"))

    print("── 12. stats(): shape del snapshot")
    st = mem.stats()
    check("stats(): claves del contrato (per_type, per_status, candidates_active, dir, corrupted_lines)",
          all(k in st for k in ("per_type", "per_status", "candidates_active",
                                "dir", "corrupted_lines"))
          and set(st["per_type"]) == {"EPISODIC", "SEMANTIC", "PROCEDURAL",
                                      "FACTUAL"}
          and st["per_status"].get("retired", 0) >= 1
          and st["corrupted_lines"] >= 1, str(st)[:160])
    check("stats(): candidates_active == 1 y dir apunta al sandbox",
          st["candidates_active"] == 1 and st["dir"].startswith(str(_TMP)))

    print(f"\n═══ {OK} OK · {FAIL} fallos ═══")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
