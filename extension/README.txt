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
