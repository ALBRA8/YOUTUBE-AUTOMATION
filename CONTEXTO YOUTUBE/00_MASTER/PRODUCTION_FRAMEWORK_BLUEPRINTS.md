# ALBRA — PRODUCTION FRAMEWORK Y BLUEPRINTS DE LÍNEA
**Ubicación:** `CONTEXTO YOUTUBE/00_MASTER/PRODUCTION_FRAMEWORK_BLUEPRINTS.md`  
**Fecha:** 2026-10-23  
**Estado:** DISEÑO CONCEPTUAL DOCUMENTADO — NO EQUIVALE A IMPLEMENTACIÓN EN CÓDIGO

## 1. Decisión arquitectónica

YOUTUBE-AUTOMATION admite múltiples líneas de producción audiovisual. No se construirá un único Blueprint universal. Se utilizará un **Production Framework común** y un Blueprint especializado por línea.

```text
IDEA + REQUISITOS
  → SELECCIÓN DE LÍNEA
  → PRODUCTION FRAMEWORK + BLUEPRINT
  → CREATIVE ENGINE
  → CREATIVE SPECIFICATION + PRODUCTION JSON
  → VALIDACIÓN
  → YOUTUBE-AUTOMATION
  → GENERACIÓN + EDICIÓN
  → CONTROL DE CALIDAD + ENTREGA
```

El Framework define el contrato común. Cada Blueprint define la gramática especializada de su línea. El Creative Engine decide qué crear; YOUTUBE-AUTOMATION ejecuta cómo producirlo.

## 2. Límites de componentes

- **Production Framework:** contrato compartido, campos comunes y reglas de interoperabilidad.
- **Line Blueprints:** unidades, gramática, invariantes, variables, restricciones y controles de calidad de cada línea.
- **Creative Engine:** interpreta idea, requisitos, Blueprint y conocimiento; entrega especificación creativa y Production JSON. No es operador de navegador ni controlador de Flow.
- **Reverse Engineering Engine:** herramienta independiente que analiza referencias, obtiene observaciones, reconstruye prompts y extrae gramática candidata. Puede alimentar cualquier Blueprint; no forma parte del Framework ni de una línea.
- **NotebookLM / fuentes:** capa de conocimiento, canon, documentación y evidencia; no sustituye el Blueprint ni la autoridad del usuario.
- **YOUTUBE-AUTOMATION:** orquestación y ejecución audiovisual: proveedores, generación, edición, renderizado, QA y entrega.
- **GoogleFlowMCP:** adaptador técnico; no decide creativamente qué producir.
- No crear un agente por Blueprint ni duplicar Creative Engine o pipeline.

## 3. Production Framework v1.0

Contrato conceptual de referencia:

```json
{
  "production": {},
  "creative_spec": {},
  "assets": {},
  "sequence": [],
  "continuity": {},
  "execution_requirements": {},
  "quality_control": {},
  "delivery": {}
}
```

Campos esperados:
- `production`: production_id, title, production_line, blueprint_id, blueprint_version, format, language, target_platforms, status.
- `creative_spec`: concept, purpose, story/world/characters cuando aplique, narrative/structure, visual_direction y audio_direction.
- `assets`: characters/creators, images, videos, audio, music, voice, products y references, según aplique.
- `sequence`: unidades temporales. La estructura interna y longitud dependen del Blueprint; no existe una cantidad universal de clips.
- `continuity`: characters, locations, objects, relationships, timeline, world_state y unresolved, cuando aplique.
- `execution_requirements`: generación, cámara, resolución, relación de aspecto, duración, audio, subtítulos, edición y referencias, según aplique.
- `quality_control`: checks requeridos, constraints, continuidad, assets, timing, prompts y estado.
- `delivery`: outputs, artifacts, metadata y publishing.

Los esquemas definitivos deberán marcar campos obligatorios, opcionales y condicionales. No asumir que este JSON conceptual ya está implementado o validado por el motor.

## 4. Production Line Registry inicial

| ID | Blueprint ID | Propósito distintivo | Estado documental |
|---|---|---|---|
| `microdrama` | `microdrama_vertical_series_5x60` | Miniserie dramática serializada | Diseño v1.0 |
| `short` | `short_vertical_v1` | Short de entrada rápida y payoff | Diseño v1.0 |
| `short_form` | `short_form_production_v1` | Producción audiovisual corta con secuencia desarrollada | Diseño v1.0 |
| `ugc` | `ugc_creator_content_v1` | Contenido estilo creador, experiencia y demostración | Diseño v1.0 |

El registro es ampliable. Líneas futuras (por ejemplo, documental, recetas, musical, educativo, anuncios o faceless) no deben forzarse dentro de un Blueprint si su gramática exige uno distinto.

## 5. Microdrama Blueprint v1.0

**ID:** `microdrama_vertical_series_5x60`  
**Unidad jerárquica:** miniserie → episodio → clip → acción → estado final.

Parámetros de diseño de esta línea:
- 5 episodios × 60 segundos = 300 segundos.
- 6 clips por episodio, 10 segundos por clip, 30 clips total.
- Vertical 9:16 y diálogo en español.
- Límite de diseño de referencia: máximo 12 palabras por clip.
- Google Flow/Omni como objetivo sujeto a capacidades documentadas y verificadas; referencias de personaje con Nano Banana/Characters solo según flujo disponible.

Gramática serial:
- E1: incidente inducido.
- E2: escalada/complicación.
- E3: punto de giro/clímax intermedio.
- E4: caída/reagrupación.
- E5: resolución y/o nuevo gancho.

Gramática por episodio: hook → situación/desarrollo → giro menor → reacción/escalada → clímax → micro-cliffhanger. El cliffhanger debe cambiar el estado o plantear una pregunta real; no basta con “continuará”.

Continuidad relevante: identidad y apariencia, vestuario, ubicación, objetos y posiciones, relaciones, cronología, estado físico/emocional, conocimiento de personajes, acción previa, conflicto y preguntas abiertas. El estado final de una unidad debe ser compatible con el inicio de la siguiente cuando hay continuidad.

Referencia de personaje: centrada en rostro, cabello, rasgos, vestuario y presentación neutral; no contaminar con escenas, acciones o trama. Prompt de clip: un párrafo continuo que incluya formato, entorno, personajes, acción, cámara, iluminación, diálogo y estado final. Las reglas técnicas de Omni/Flow deben proceder de fuentes autorizadas o pruebas reales.

Invariantes de línea: 5 episodios, 60 s por episodio, 6 clips por episodio, 10 s por clip, 30 clips, 9:16, diálogo en español, límite de referencia de 12 palabras, continuidad y micro-cliffhanger. No trasladar estas restricciones a las otras líneas.

## 6. Short Blueprint v1.0

**ID:** `short_vertical_v1`. Duración, número de unidades, personajes, diálogo, cliffhanger y estructura dramática son flexibles.

Tipos: narrativo, educativo, informativo, visual, transformación, demostración, curiosidad, listas, reacción y storytelling.

Unidad flexible: Short → segmentos → planos/clips → acción/información → estado/payoff.

Gramática de referencia: hook → contexto/setup → desarrollo → escalada/información → payoff → final. Se pueden omitir etapas; algunos Shorts funcionan como hook → payoff.

Hooks posibles: visual, narrativo, informativo, curiosidad, emocional, sorpresa, pregunta, contradicción, transformación o resultado primero. El payoff puede ser respuesta, resultado, transformación, revelación, demostración, comparación, chiste, solución, conclusión o descubrimiento; debe cumplir la expectativa creada.

Finales: resolución, revelación, conclusión, transformación, reacción, loop, callback, pregunta abierta o continuación. No todos necesitan cliffhanger.

Retención de referencia: expectativa → información → cambio → nueva expectativa → payoff. Evitar ganchos artificiales. No hay límite universal de palabras para diálogo; se ajusta a duración, idioma e inteligibilidad. Separar gramática de generación y de edición.

Invariantes: propósito claro, unidades funcionales, legibilidad móvil cuando aplique, progresión identificable, payoff o final deliberado, coherencia visual y continuidad cuando sea necesaria.

## 7. Short-Form Blueprint v1.0

**ID:** `short_form_production_v1`. Línea para piezas audiovisuales cortas cuya secuencia puede estar más desarrollada que un Short de impacto inmediato, sin duración ni número fijo de escenas.

Tipos candidatos: mini historias independientes, narración visual, recetas/procesos, transformaciones, piezas cinematográficas breves, storytelling de marca, explicaciones visuales, entretenimiento, musicales/atmosféricas y piezas multiescena.

Unidad flexible: producción → concepto → secuencia → escena → plano/clip → acción/estado → montaje final. Cada unidad puede definir id, tipo, propósito, inicio, duración, visual, acción, diálogo, audio, continuidad de entrada/salida y requisitos de generación/edición.

Gramática de referencia: entrada → contexto → desarrollo → progresión → payoff → final. No es obligatorio usar todas las etapas. Si hay historia, definir premisa, objetivo, personajes, conflicto, progresión, cambio de estado, resolución y consecuencia. Para recetas, demostraciones o piezas atmosféricas no inventar personajes o conflictos innecesarios.

Variables: tema, audiencia, duración, plataforma, tipo, complejidad, escenas/personajes, estilo visual/sonoro, ritmo, realismo, idioma, recursos y final. Invariantes: propósito, unidades funcionales, coherencia audiovisual, separación generación/edición, requisitos explícitos y QC verificable.

## 8. UGC Blueprint v1.0

**ID:** `ugc_creator_content_v1`. Línea para contenido de estilo creador, experiencias, reseñas, demostraciones y propuestas de valor.

Tipos: testimonio/experiencia, reseña, tutorial/demostración, unboxing, problema-solución, recomendación, comparativa, storytelling de experiencia, anuncio con estética UGC y respuestas a preguntas frecuentes.

Distinguir UGC realmente creado por usuarios de publicidad que imita su estilo. No presentar testimonios sintéticos como experiencias reales verificadas ni inventar credenciales. Las afirmaciones comerciales deben tener soporte y cumplir las restricciones legales aplicables.

Gramática de referencia: hook → contexto personal → problema/necesidad → experiencia/demostración → resultado/conclusión → CTA si procede. Puede simplificarse según el contenido.

Campos del creador: identidad, rango de edad, apariencia, vestuario, personalidad, forma de hablar, estilo de entrega, tono emocional, relación con cámara y referencias. Variables visuales: encuadre, movimiento, entorno, luz, vestuario, visibilidad del producto/demostración, autenticidad visual, intensidad de edición y rótulos.

El diálogo debe ser natural, inteligible y sincronizado; sin límite universal de palabras. Generación (presentador, gestos, producto, entorno, diálogo) y edición (selección, cortes, subtítulos, música, efectos, CTA y exportación) permanecen separadas.

Continuidad, cuando aplique: identidad/apariencia/vestuario del creador, identidad y estado del producto, ubicación, secuencia de acciones, afirmaciones pronunciadas, estado de demostración y referencias. Invariantes: objetivo comunicativo, afirmaciones respaldadas, representación honesta, continuidad pertinente, audio inteligible y requisitos técnicos explícitos.

## 9. Selección, validación y autoridad

Flujo:
`IDEA + USER REQUIREMENTS → LINE SELECTION → LOAD BLUEPRINT → CREATIVE ENGINE → CREATIVE SPEC → PRODUCTION JSON → CONTRACT VALIDATION → YOUTUBE-AUTOMATION → GENERATION/EDITING → QC → DELIVERY`.

Reglas:
1. El usuario puede elegir la línea explícitamente.
2. Si no lo hace, el Creative Engine propone la más adecuada según intención y restricciones.
3. Si varias interpretaciones razonables afectan una decisión importante, no asumir sin fundamento.
4. El Blueprint define gramática especializada; el Framework define el contrato común.
5. Validar campos, referencias, restricciones y compatibilidad técnica antes de ejecutar.
6. No simular éxito si falta una capacidad; registrar el bloqueo.
7. Reutilizar el Creative Engine y pipeline existentes, sin crear cuatro motores independientes.

Jerarquía de autoridad: requisitos explícitos del usuario → requisitos del proyecto → Production Framework → Blueprint de línea → conocimiento/fuentes → Creative Engine e inferencias justificadas → Production Specification/JSON → ejecución. Las fuentes no pueden invalidar requisitos explícitos del usuario.

## 10. Relación con Reverse Engineering y NotebookLM

Reverse Engineering Engine sigue siendo independiente y transversal:
`REFERENCE → OBSERVATIONS → RECONSTRUCTED PROMPT → PRODUCTION GRAMMAR → BLUEPRINT CANDIDATE`.

NotebookLM/fuentes aportan conocimiento, canon, documentación y evidencia. No reemplazan el Blueprint ni se convierten en director creativo o motor de producción. Separar contenido, lenguaje visual, gramática de producción e instrucciones de generación.

## 11. Estado y próximos pasos

**Lo documentado aquí es diseño conceptual construido en conversación; no es prueba de que los Blueprints, schemas o selector ya existan en código.**

Siguiente trabajo de implementación:
1. Versionar Framework y Blueprints como artefactos canónicos.
2. Definir JSON Schema o validador equivalente para Framework y cada línea.
3. Implementar/registrar selector de línea sin duplicar Creative Engine.
4. Añadir pruebas de contrato por línea, incluyendo datos inválidos, campos condicionales, referencias ausentes y capacidades no disponibles.
5. Integrar en modo seguro con YOUTUBE-AUTOMATION.
6. Ejecutar pruebas reales y documentar resultados con SHAs y evidencia.
7. Actualizar el CONTEXTO YOUTUBE y su INDEX al completar cada hito.

No declarar código, tests, integración o publicación como realizados hasta verificarlos.
