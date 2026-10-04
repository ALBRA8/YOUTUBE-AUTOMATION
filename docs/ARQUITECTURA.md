# ARQUITECTURA — YOUTUBE AUTOMATION

> Versión del documento: 1.0 · 2026-10 · congelada tras el análisis de evolución v2.0→v2.12.2
> Este documento es la ley del proyecto. Toda construcción nueva debe justificarse aquí.
> Fuentes de la decisión: `arquitectura.txt`, `PROMPT_MAESTRO_HISTORIAS_MEXICANAS.txt`,
> método TikTok Shop (collage + HTML), auditoría externa (commit 0cae11b) y el estado real del código.

---

## 1. Una frase

> **El nicho es un paquete de datos (playbook) que viste al cerebro creativo; el contrato JSON es el
> idioma común; el builder es un obrero que ejecuta el contrato sin saber de qué nicho viene.**

---

## 2. Qué aprendió la evolución (v2.0 → v2.12.2)

| Era | Aportó | Lección |
|---|---|---|
| v2.0–2.7 | Núcleo URL→guion→video, estilos, temas, biblioteca | El builder completo ya existía y funciona |
| v2.10–2.11 | Rescate tras barrido, árbol Proyectos▸Nichos▸video, Avatar DNA, recetas de cámara | Los datos SON el proyecto; el código se puede reconstruir, la DB no |
| v2.12.0–2.12.1 | VÓRTICE + CEREBROS (6 modelos NVIDIA, failover, visión) | El cerebro creativo es INTERCAMBIABLE — nadie ata el sistema a un proveedor |
| v2.12.2 | Backups automáticos + música, de la auditoría externa | Resiliencia primero: la fábrica debe sobrevivir desastres |

**Hallazgo central del análisis (2026-10):** el sistema YA tenía sin saberlo las piezas de la
arquitectura objetivo — contrato `guion_json` + validador + 3 puertas de entrada (UI, API, MCP)
+ orchestrator + proveedores de imagen con fallback + FFmpeg. Lo que faltaba era que **el nicho
fuera ciudadano de primera clase**: hoy los nichos viven dispersos en txt sueltos, en
`if/else` de `flow_export.py` y en la memoria de ChatGPT. Eso es lo que esta arquitectura corrige.

---

## 3. Las cuatro capas

```
┌─────────────────────────────────────────────────────────┐
│ 1. PLAYBOOKS DE NICHO            ← AQUÍ vive el nicho   │
│    prompt maestro por etapa · elenco privado            │
│    ejemplos de oro · estructura · prohibiciones         │
│    (DATA versionada, no código)                         │
└──────────────────────────┬──────────────────────────────┘
                           │ el repo COMPILA: idea + playbook + contrato
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 2. CEREBRO(S) CREATIVO(S) — uno por etapa, intercambiable│
│    ChatGPT web (gratis) · Gemini web (gratis)           │
│    CEREBROS NVIDIA internos (VÓRTICE) · Gemini API      │
│    NO saben nada de Flow, FFmpeg ni del repo            │
└──────────────────────────┬──────────────────────────────┘
                           │ production.json — SIEMPRE el mismo contrato
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 3. CONTRATO DE PRODUCCIÓN (invariante)                  │
│    project · characters · chapters · scenes             │
│    prompt_imagen · prompt_video · dialogue · camara     │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│ 4. BUILDER (invariante)                                 │
│    validator → orchestrator → providers → FFmpeg        │
│    No sabe qué nicho fue. Le da igual.                  │
└─────────────────────────────────────────────────────────┘
```

**Regla de oro:** el nicho solo vive en la capa 1. Si un nicho necesita un `if` en el builder,
el diseño está mal.

### Regla de enrutamiento de cerebros ("cada uno mejor en lo suyo")

Una etapa elige su cerebro por competencia, no por comodidad:

| Cerebro | Es mejor en | Costo |
|---|---|---|
| **Gemini web** | Imágenes con múltiples referencias (identidad+producto) | gratis |
| **ChatGPT web** | Análisis visual de imágenes + redacción comercial/narrativa larga | gratis |
| **CEREBROS NVIDIA** (VÓRTICE) | Automatización interna: acciones en la fábrica, planes JSON, visión rápida | gratis (API NVIDIA) |
| **Gemini API** | Guion estructurado dentro del pipeline sin humano en el medio | cuota free tier |
| **repo (código)** | Recortes, parseo, renombrado, validación — precisión matemática | $0 |
| **fábrica (builder)** | TTS, montaje, subtítulos, publicación | $0–bajo |

**Puerta principal de esta era: manual y gratis.** El repo prepara cada etapa (prompt compilado,
botón "copiar", zona para soltar el artefacto de vuelta), el usuario ejecuta en la web del cerebro.
La automatización por API llega después y NO cambia ni el contrato ni los playbooks — solo la
capa de ejecución de la etapa.

---

## 4. El contrato de producción (evolución v1 → v2)

### v1 (hoy, vigente — `services/guion_json.py`)

```json
{ "titulo": "...", "formato": "short", "estilo": "auto",
  "camara": "cine_anamorfico",
  "escenas": [ { "titulo", "narracion", "prompt_imagen",
                 "camara?", "outfit?", "ambiente?" } ],
  "cta?": "...", "auto_start": false }
```

### v2 (objetivo — retrocompatible con v1)

```json
{
  "project":   { "titulo", "formato", "estilo", "camara", "nicho?" },
  "characters":[ { "id", "name", "description", "reference_prompt",
                   "imagen_referencia?" } ],
  "chapters":  [ { "id", "titulo?",
      "scenes": [ { "titulo", "hook?",
                     "narracion" | "dialogue",      ← lipsync cae aquí
                     "prompt_imagen", "prompt_video?",
                     "camara?", "outfit?", "ambiente?",
                     "movimiento?", "cta?",
                     "imagen": { "via": "collage", "panel": 3 } } ] } ],
  "render":    { "resolucion": "1080x1920", "fps": 30 }
}
```

Reglas de compatibilidad (obligatorias):

1. **Un JSON v1 sigue siendo válido en v2**: se interpreta como 1 capítulo, 0 personajes.
2. Campos nuevos (`prompt_video`, `dialogue`, `movimiento`, `imagen.via`) son **opcionales**:
   el builder los usa si el proveedor de turno los soporta y los ignora si no.
3. El validador v2 valida v1 y v2; los errores 400 siguen el ciclo GPT→corrige→reintenta.
4. `GET /api/guion_json/contrato` publicará siempre el spec vivo de la versión activa.

### Un contrato, tres mundos (probado con casos reales)

| Nicho | Se expresa como |
|---|---|
| Barrio Mexicano | 1 capítulo, 10 escenas, `characters` = elenco de 4, `narracion` = lipsync |
| Frutinovelas | N capítulos, `characters` = frutas/caricaturas del playbook |
| TikTok Shop | 1 capítulo, 6 escenas, `imagen.via: "collage"`, `dialogue` = lipsync comercial |

---

## 5. Playbooks de nicho

### 5.1 Qué es un playbook

Un **paquete de datos versionado** que contiene TODO lo que un cerebro necesita para producir
de ese nicho, y nada de lo que es del builder:

```
backend/playbooks/<nicho>/
├── playbook.json      ← metadatos: etapas, cerebros, estructura, prohibiciones, contrato
├── prompts/           ← textos verbatim por etapa (la ley creativa del nicho)
├── elenco/            ← personajes PRIVADOS del nicho (fichas + anclas en inglés)
├── ejemplos/          ← guiones/campañas de oro para few-shot
└── assets/            ← plantillas del nicho (p. ej. HTML universal base)
```

### 5.2 Decisiones de diseño ya tomadas (no renegociar sin causa)

1. **Elenco privado por playbook.** "Valeria" fotorealista (Barrio Mexicano) y "Valeria" glossy 3D
   (Valeria influencer) son personajes DISTINTOS que casualmente comparten nombre. El día que se
   globalicen los avatares, una generación romperá la coherencia visual de un nicho entero.
2. **Crossover = excepción futura, no default.** Mezclar caricaturas con hiperrealistas solo tiene
   sentido en casos tipo "¿Quién engañó a Roger Rabbit?" — se implementará como flag `crossover`
   que referencia personajes de OTRO playbook, nunca como elenco global.
3. **Los ejemplos de oro son parte del playbook.** Un nicho sin ejemplo de oro no está empacado.
4. **Un nicho puede ser multi-etapa con cerebro distinto por etapa** (ver TikTok Shop). El playbook
   declara la cadena completa: entradas, prompt, salida y por qué ese cerebro.
5. **El repo hace lo mecánico.** Recortar un collage 2×3, parsear `const ideas=[...]` de un HTML,
   renombrar paneles: código puro, $0, exacto. La IA solo donde crea valor.

### 5.3 Catálogo real de nichos (inventario 2026-10)

| Nicho | Estado | Fuente original |
|---|---|---|
| 🏘️ barrio-mexicano | **EMPACADO** | `PROMPT_MAESTRO_HISTORIAS_MEXICANAS.txt` |
| 🛍️ tiktok-shop | **EMPACADO** (multi-cerebro 4 etapas) | método collage+HTML + zip Gymshark |
| 🍓 frutinovelas/caricaturas | pendiente | `NOVELA DE CARICATUIRAS PROMPTS MAESTRO.txt` |
| 👑 valeria-influencer | pendiente | `La_Influencer_Vitiligo_Bloc_FINAL VALERIA.txt` |
| 🍯 recetas-jp | pendiente | `PRO Receta Natural naranja... .txt` |
| ⚽ cr7-primitive | pendiente | `CRISTIANO_RONALDO_PRIMITIVE_VIRAL.txt` |
| 🔨 artesano (palma+pino) | pendiente | `PROMPT EJEMPLO.txt` (= modo `artesano` de flow_export) |
| 🏗️ transformacion | pendiente | modo `transformacion` de flow_export.py |

**Regla de empacado:** cada playbook se crea COPIANDO verbatim sus textos (nunca reescribirlos:
son método probado del usuario) y extrayendo a JSON solo lo estructural (elenco, estructura,
prohibiciones). Los archivos fuente de `upload/` quedan como respaldo histórico.

---

## 6. El builder (capa 4 — ya construida)

Componentes existentes que NO se tocan en la Fase 1-2, y su papel en la arquitectura:

| Componente | Papel arquitectónico |
|---|---|
| `pipeline/orchestrator.py` | Job manager: colas, eventos SSE, cancelación, zombi-recovery |
| `pipeline/images.py` | IMAGE_PROVIDER con cadena de fallback: Gemini API → z-ai → extensión → placeholder |
| `pipeline/video.py` | VIDEO ENGINE (FFmpeg): montaje, música, sidechain |
| `pipeline/tts_step.py` + `services/tts_service.py` | VOICE (edge $0 / gemini premium) |
| `pipeline/subtitles.py` + `whisper_service.py` | SUBTÍTULOS palabra a palabra |
| `services/guion_json.py` | VALIDATOR del contrato (parse/validate/spec) |
| `services/mcp_server.py` | Puerta MCP: 12 tools JSON-RPC (contrato v1) |
| `services/backup.py` | Resiliencia: DB+token+.env con rotación 14 |
| `extension/` | Browser automation hacia Flow (proveedor de video) |
| `pipeline/flow_export.py` | ⚠️ Deuda de arquitectura: 1764 líneas con 3 nichos escondidos como modos. Su conocimiento se extraerá a playbooks; el módulo quedará como exportador técnico |

---

## 7. Plan de migración (sin romper la fábrica nunca)

Cada fase termina en: E2E verde + worklog + commit + push. Nada de esto toca el builder salvo
donde se indica.

### FASE 0 — Congelar el diseño ✅ (esta versión)
- [x] `docs/ARQUITECTURA.md` (este documento)
- [x] Playbooks empacados: `barrio-mexicano`, `tiktok-shop`
- [x] Contrato v1 intacto, fábrica intacta

### FASE 1 — Playbooks vivos en el sistema
- [ ] `services/playbooks.py`: loader de `backend/playbooks/*/playbook.json` (+validación de esquema)
- [ ] Endpoints: `GET /api/playbooks`, `GET /api/playbooks/{id}`, `GET /api/playbooks/{id}/etapa/{n}` (devuelve prompt compilado)
- [ ] UI: selector de nicho + visor de etapas con botón "Copiar prompt de esta etapa" y zona de arrastre para el artefacto de vuelta (collage.png / html_final.html)
- [ ] Extractor TikTok Shop mínimo: recorte collage 2×3 → 6 paneles + parse `const ideas` → JSON descargable
- [ ] Empacar playbooks restantes (frutinovelas, valeria-influencer, recetas-jp, cr7, artesano, transformacion)

### FASE 2 — Contrato v2 (retrocompatible)
- [ ] `guion_json.py`: aceptar `characters` + `chapters[].scenes` (v1 sigue valido: normalización v1→v2)
- [ ] Validaciones extra por playbook (elenco ⊆ cast, hablantes coherentes, presupuesto de diálogo)
- [ ] Spec vivo en `/api/guion_json/contrato` muestra v2
- [ ] MCP: `crear_video_guion_json` entiende v2 sin romper v1

### FASE 3 — TikTok Shop dentro de la fábrica
- [ ] Modo `tiktok_shop` en pipeline: panel_i + lipsync_i → TTS → clip 9:16 → multipanel final opcional
- [ ] Renderizador de HTML base desde `ideas.json` (el repo puede regenerar el HTML sin ChatGPT)
- [ ] Un nicho de story-telling (barrio-mexicano) probado end-to-end desde playbook → guion v2 → fábrica

### FASE 4 — Cerebros internos en las etapas (opcionalidad)
- [ ] Cada etapa del playbook puede declarar `cerebro_interno: "deepseek|gpt-oss|llama-90b..."` para ejecutarse SIN humano vía CEREBROS NVIDIA (con visión donde haga falta)
- [ ] VÓRTICE gana acción "ejecutar etapa del playbook"
- [ ] Extracción final del conocimiento de `flow_export.py` a playbooks (deuda saldada)

### FASE 5 — Automatización de puertas (solo si hay venta)
- [ ] API OpenAI/Gemini de pago como ejecutor de etapas (mismo contrato, otra puerta)
- [ ] Métricas por nicho (costo/tiempo/tasa de aceptación de ideas)

### Anti-objetivos (lo que NO haremos — lecciones `arquitectura.txt` §17 + decisión 2026-10)
- ❌ Que el cerebro creativo controle Chrome/Flow directamente
- ❌ Credenciales dentro de prompts
- ❌ Un formato creativo por proveedor (el proveedor se elige en el builder, no en el JSON)
- ❌ Elenco global compartido entre nichos
- ❌ Reescribir los prompts verbatim del usuario al empacarlos
- ❌ Reemplazar VÓRTICE/trends por esta arquitectura (VÓRTICE se INTEGRA como cerebro interno, Fase 4)

---

## 8. Convenciones del proyecto (vivas)

- Idioma: todo en español (código, UI, docs, commits)
- Toda cambio: E2E real → worklog (`/home/z/my-project/worklog.md`) → commit con mensaje de versión → push a GitHub (`ALBRA8/YOUTUBE-AUTOMATION`, procedimiento subtree en worklog Task 24)
- Versionado semántico pragmático: PATCH=fix, MINOR=feature, y el cache-bust de `index.html` siempre al bump
- Datos > código: la DB, token.json y .env tienen backup automático (`services/backup.py`); los playbooks viven en git
- Antes de construir: revisar este documento. Si la construcción no cabe aquí, primero se enmienda aquí.
