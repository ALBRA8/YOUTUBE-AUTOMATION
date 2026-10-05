================================================================================
FLOW SCRIPT PROCESSOR — INSTALACION Y OPERACION (version 2.0, sin compilacion)
================================================================================
Replica fiel de "IMAGENES FLOW_EXT" (manual EXTENSION TOUTUBE) reescrita en
JavaScript puro: NO requiere npm ni build. Cargas la carpeta directamente.

--------------------------------------------------------------------------------
PASO 1: Instalacion en Google Chrome
--------------------------------------------------------------------------------
1. Abre Google Chrome y escribe en la barra de direcciones: chrome://extensions/
2. En la esquina superior derecha, activa el interruptor "Modo de desarrollador".
3. En la esquina superior izquierda, haz clic en "Cargar descomprimida".
4. Selecciona ESTA carpeta (la que contiene este README y manifest.json).
5. La extension "Flow Script Processor" aparecera instalada con su icono.

NOTA: si ya tenias una version anterior cargada, haz clic en el boton de
recarga (⟳) de la tarjeta de la extension despues de reemplazar los archivos.

--------------------------------------------------------------------------------
PASO 2: Procedimiento operativo
--------------------------------------------------------------------------------
1. Abre una pestana y entra a tu herramienta en Google Labs (Flow / ImageFX):
   https://labs.google/fx/...
2. Abre el icono de la extension en la barra superior.
3. Haz clic en "Vincular Proyecto" y selecciona la carpeta del proyecto en tu
   disco (la que contiene out/ideas/... o el script.json).
   - Chrome pedira confirmacion: "La extension desea ver y editar archivos en
     esta carpeta" → clic en "Ver y editar" (se pide una vez por sesion).
4. Aparecera la insignia verde: "Guardando directo en: [NOMBRE]" y
   "script.json (Autodetectado) (N escenas listas)".
   - La busqueda es inteligente: encuentra out/ideas/idea_000XXX/script.json
     con el numero de idea MAS ALTO (buscador recursivo findScriptJson).
   - Plan B si no hay carpeta: boton "Subir JSON" y elige el script.json.
5. Selecciona el Tipo de Contenido (Imagenes PNG / Videos MP4-WebM) y la
   cantidad de imagenes por escena (1/2/4/6).
6. Presiona "Iniciar Generacion".
7. La extension tomara el control:
   - Escribe cada prompt en el editor de Flow simulando mecanografia humana.
   - Espera 45s entre inyecciones (anti-bloqueo) y procesa hasta 3 escenas
     en paralelo (1 en modo video).
   - Intercepta el trafico tRPC, asocia cada resultado con su escena y guarda
     los archivos DIRECTO en disco: Escena_01/imagen_1.png, Escena_01/video_1.mp4 ...
   - Si Google muestra "Generating too quickly", pausa 90 segundos y reintenta
     solo (las escenas pasan a color naranja).
   - Si Google bloquea por politicas, la escena queda en rojo y la cola sigue;
     puedes pulsar "Reintentar" en la tarjeta.
8. Al terminar: barra al 100% y todas las tarjetas en verde.

--------------------------------------------------------------------------------
REsilencia MV3
--------------------------------------------------------------------------------
El estado (cola, progreso, mapeos) se guarda en chrome.storage.session. Si
Chrome suspende el Service Worker (30s de inactividad), al despertar recupera
la cola y continua donde quedo. Un keepalive por alarmas reactiva el sondeo.

--------------------------------------------------------------------------------
PUENTE BACKEND (Flow Bridge) — v2.1 (bridge.js)
--------------------------------------------------------------------------------
QUE ES: la extensión puede trabajar como "worker" de un backend local. El
backend guarda la cola de jobs (un asset por escena: imagen o vídeo) y la
extensión los reclama, los genera en labs.google con la maquinaria de siempre
(inyección Slate + sondeo DOM + descarga) y sube el resultado al backend.
LOS PROMPTS VIENEN DEL BACKEND: son el script.json generado por
build_script_json en el proyecto (backend/pipeline/flow_export.py); la
extensión NUNCA los inventa ni los edita.

COMO ACTIVARLO:
1. Arranca el backend (uvicorn; por defecto http://127.0.0.1:8000) y encola un
   proyecto (POST /api/extension/flow/jobs/enqueue o el panel del backend).
2. Icono de la extensión → tarjeta "Puente Backend".
3. (Opcional) despliega "Servidor / API key" y ajusta baseUrl / X-API-Key si
   tu backend define MASTER_API_KEY (header X-API-Key).
4. Botón "Puente Backend: OFF" → un clic → ON. El service worker empieza a
   sondear la cola cada 5s. Otro clic lo desactiva.

QUE HACE CADA CICLO (extension/bridge.js):
  GET  /api/extension/flow/jobs/next?worker=w-XXXXXXXX  → claim atómico (204 =
  sin jobs) → heartbeat cada 30s para extender el lease → genera el asset en
  labs.google con el mismo camino de la cola local → POST /complete con los
  bytes crudos (image/png o video/mp4) → si algo falla, POST /fail con el
  error (el backend reintenta o marca dead). Un solo job a la vez.

CONVENCION DE ASSETS (lado backend): data/output/<pid>/flow/ con
Escena_NN_flow.png (imágenes, validadas con PIL) y Escena_NN_video_<part>.mp4
(vídeos, validados con ffprobe). La extensión envía el asset tal cual lo
generó Flow; si Flow entregara WebM el backend lo rechazará (422) y el job se
reintenta.

NOTAS:
- Necesita una pestaña de labs.google con un proyecto de Flow abierto (editor
  visible). Si la cola local está en uso, el job se rechaza limpio (fail) y el
  backend lo reintenta más tarde.
- Si Chrome suspende el Service Worker a mitad de job, el lease expira y el
  backend reintenta; un keepalive por alarmas (flow-bridge-keepalive) minimiza
  estos cortes.
- El estado del puente (baseUrl, apiKey, workerId, enabled) vive en
  chrome.storage.local bajo flow_bridge_cfg_v1.

--------------------------------------------------------------------------------
Si algo falla
--------------------------------------------------------------------------------
- "Editor Slate no encontrado": abre un proyecto dentro de Flow (la caja de
  texto debe estar visible) y presiona Iniciar de nuevo.
- La insignia dice "Descargas": la carpeta no tiene permiso readwrite activo.
  Vuelve a pulsar "Vincular Proyecto" y acepta "Ver y editar".
- Los archivos caen en Descargas/FLOW_EXPORT/...: mismo motivo; la estructura
  Escena_XX/ se respeta igual y el importador de v2 los acepta.
- Cambios de codigo: recarga la extension y refresca (F5) la pestana de Flow.
================================================================================
