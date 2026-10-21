# INT-006 — INTEGRACIÓN GoogleFlowMCP (DRIVER CDP / MCP PARA GOOGLE FLOW)

**Fecha de Preparación:** 2026-10-20  
**Estado:** PUENTE IMPLEMENTADO Y PROBADO (DESACTIVADO POR DEFECTO CON FLOW_MCP_ENABLED=0)  
**Ubicación Definitiva:** `D:\PROYECTOS\YOUTUBE AUTOMATION\tools\GoogleFlowMCP`  
**Origen:** `srzGoogleFlowMCP.zip` (Downloads)

---

## 1. Propósito y Alcance

Proveer una capacidad complementaria o alternativa de automatización directa del navegador para Google Flow mediante el **Model Context Protocol (MCP)**, utilizando `playwright-core` sobre el protocolo **Chrome DevTools Protocol (CDP)** en el puerto 9333.

> **Regla de frontera:** En esta fase de preparación, el componente NO se encuentra conectado al pipeline de producción ni se ha ejecutado ninguna generación real en Flow. Solo se ha auditado, instalado, blindado y probado herméticamente en local.

---

## 2. Inventario de Archivos

| Archivo / Carpeta | Función | Clasificación |
| :--- | :--- | :--- |
| `package.json` | Metadatos y dependencias declaradas (`engines.node >= 18`) | Imprescindible |
| `package-lock.json` | Bloqueo determinista de 95 dependencias | Imprescindible |
| `src/mcp.js` | Punto de entrada del servidor MCP stdio (McpServer v1.0.1) | Imprescindible |
| `src/flow.js` | Lógica de interacción con Google Flow (ProseMirror, settings, upload, assets) | Imprescindible |
| `src/chrome.js` | Detección de binario Chrome y spawn con flags CDP y perfil dedicado | Imprescindible |
| `src/lock.js` | Mecanismo de exclusión mutua cross-process (`.flow.lock/pid`) | Imprescindible |
| `src/cli.js` | Interfaz de línea de comandos para control manual y login inicial | Imprescindible |
| `test/lock.test.js` | Pruebas unitarias de concurrencia y recuperación de locks | Desarrollo / Pruebas |
| `.gitignore` | Exclusiones locales de seguridad (node_modules, state, config, output, inputs) | Seguridad |
| `inputs/.gitkeep` | Directorio para imágenes de referencia locales | Runtime local |
| `output/.gitkeep` | Directorio para descargas de imágenes generadas | Runtime local |
| `README.md` | Documentación operativa de usuario | Documentación |
| `CLAUDE.md` | Guía de instalación y troubleshooting de referencia | Documentación |
| `AGENTS.md` | Metadatos de integración para agentes | Documentación |
| `examples/referencia-producto.txt` | Ejemplo de prompt con `@` | Ejemplo |

---

## 3. Dependencias y Requisitos Confirmados

- **Node.js:** Versión instalada `v24.14.0` (cumple `engines.node >= 18`). Ubicación: `C:\Program Files\nodejs\node.exe`.
- **npm:** Versión instalada `11.9.0`.
- **Dependencias declaradas:**
  - `@modelcontextprotocol/sdk`: `^1.31.0` (Protocolo MCP estándar)
  - `playwright-core`: `^1.63.0` (Librería CDP ligera sin descarga de navegadores adicionales)
  - `zod`: `^4.6.5` (Validación de esquemas de herramientas)
- **Instalación:** Ejecutado `npm ci` con éxito (95 paquetes instalados, 0 vulnerabilidades).

---

## 4. Mapa de Rutas Reales y Comportamiento de Rutas

- **Resolución de Raíz (`ROOT`):** Dinámica vía `path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')`. Funciona independientemente del nombre del directorio y tolera espacios en la ruta (`YOUTUBE AUTOMATION`).
- **Ubicación de Chrome:** `C:\Program Files\Google\Chrome\Application\chrome.exe` (detectada automáticamente en Windows).
- **Perfil de Usuario de Chrome (`userDataDir`):** `%LOCALAPPDATA%\FlowImageChrome` (ubicado fuera del repositorio de trabajo, evitando contaminación de Git).
- **Archivos de Estado / Configuración:**
  - `config.json` (ruta absoluta a carpeta de salida, opcional).
  - `state.json` (persistencia del `projectId` actual de Flow).
  - `.flow.lock` (directorio temporal con PID de proceso).
- **Archivos de Medios:**
  - `output/` (imágenes generadas).
  - `inputs/` (referencias locales del usuario).

---

## 5. Exclusiones de Seguridad

Se configuró el archivo `tools/GoogleFlowMCP/.gitignore` para asegurar que ningún artefacto sensible llegue a Git:

```gitignore
node_modules/
config.json
state.json
.flow.lock/
output/*
!output/.gitkeep
inputs/*
!inputs/.gitkeep
*.log
npm-debug.log*
```

---

## 6. Configuración Prevista para Antigravity

Bloque a integrar en `C:\Users\Johan\.gemini\config\mcp_config.json`:

```json
{
  "mcpServers": {
    "google-flow-mcp": {
      "command": "C:\\Program Files\\nodejs\\node.exe",
      "args": [
        "D:\\PROYECTOS\\YOUTUBE AUTOMATION\\tools\\GoogleFlowMCP\\src\\mcp.js"
      ]
    }
  }
}
```

---

## 7. Pruebas Realizadas y Resultados

1. **Pruebas Unitarias de Concurrencia (`test/lock.test.js`):**
   - Script ajustado en `package.json` a `"test": "node --test"` para compatibilidad nativa en Windows.
   - Serialización de llamadas concurrentes: PASS
   - Liberación de lock ante excepciones: PASS
   - Recuperación de lock ante proceso muerto: PASS
   - Total: **3/3 PASS** (`npm test` duración: 570 ms).
2. **Prueba de Servidor MCP (Stdio JSON-RPC 2.0):**
   - Handshake `initialize` (protocolVersion `2024-11-05`): PASS (`srz-google-flow-mcp` v`1.0.1`).
   - Introspección `tools/list`: PASS. Expone exactamente 4 herramientas:
     - `flow_upload_file`: Sube imagen local y registra etiqueta `@{name}` (`filePath` requerido, `name`, `replace`).
     - `flow_list_assets`: Lista activos del proyecto activo de Flow.
     - `flow_generate_image`: Genera imágenes con Nano Banana (`prompt` requerido, `aspect` enum `[16:9, 4:3, 1:1, 3:4, 9:16]`, `count` 1-4, `model` enum `[2, pro, lite]`, `outDir`).
     - `flow_new_project`: Inicializa nuevo proyecto en Flow.
   - Resolución dinámica de `outDir` tolerante a espacios en `YOUTUBE AUTOMATION`: PASS (`d:\PROYECTOS\YOUTUBE AUTOMATION\tools\GoogleFlowMCP\output`).
3. **Aislamiento y Seguridad:**
   - Perfil Chrome `%LOCALAPPDATA%\FlowImageChrome`: PASS (verificado limpio/inexistente previamente).
   - Reglas de Git: PASS (`git check-ignore` verificado para `.flow.lock`, `node_modules`, `config.json`, `state.json`, `output/*`, `inputs/*`).

---

## 8. Riesgos y Decisiones Pendientes (Para Fase Siguiente)

1. **Autenticación en Flow:** Requiere que el operador humano abra la ventana dedicada de Chrome (`node src/cli.js chrome`) una única vez para iniciar sesión con su cuenta de Google.
2. **Coexistencia con Extensión:** La extensión inyectada en Chrome y el driver Playwright actúan por canales diferentes (la extensión observa el tráfico `/batchexecute`; el driver Playwright controla el DOM y los clics). Deben coordinarse para que no colisionen.
3. **Estabilidad de Selectores:** El MCP depende de clases y roles de Material Design (`div.ProseMirror`, `button.settings-trigger-button`, `flow-image-tile`). Cualquier rediseño de Google Flow podría requerir mantenimiento de selectores.
4. **Activación en Antigravity:** La configuración en `~/.gemini/config/mcp_config.json` se mantiene deliberadamente vacía hasta que se apruebe la fase de activación.

---

## 9. Diseño Técnico del Puente Orquestador ↔ GoogleFlowMCP

### 9.1 Arquitectura del Puente
El orquestador de YOUTUBE-AUTOMATION (Python/FastAPI) se comunica con `GoogleFlowMCP` mediante un cliente asíncrono tipado (`FlowMCPClient` en `backend/services/flow_mcp_client.py`) sobre el protocolo estándar **MCP Stdio (JSON-RPC 2.0)**.
- **Transmisión:** Proceso hijo de Node.js invocando `tools/GoogleFlowMCP/src/mcp.js` con stdin/stdout en UTF-8 y delimitación por saltos de línea (`\n`).
- **Aislamiento:** Controlado por el feature flag `FLOW_MCP_ENABLED=0` en `backend/config.py`. En estado inactivo o en caso de fallo, el pipeline degrada de forma natural a la cadena de planes existente (Gemini -> z-ai -> Extension -> Placeholder).

### 9.2 Contrato Mínimo de Herramientas
1. `flow_new_project`:
   - Entrada: `{}`
   - Salida: `{"ok": bool, "project_id": str, "error": str | None}`
2. `flow_upload_file`:
   - Entrada: `{"filePath": str, "name": str | None, "replace": bool}`
   - Salida: `{"ok": bool, "name": str, "media_id": str | None, "reused": bool, "error": str | None}`
3. `flow_list_assets`:
   - Entrada: `{}`
   - Salida: `{"ok": bool, "assets": list[str], "error": str | None}`
4. `flow_generate_image`:
   - Entrada: `{"prompt": str, "aspect": "16:9"|"4:3"|"1:1"|"3:4"|"9:16", "count": 1..4, "model": "2"|"pro"|"lite", "outDir": str | None}`
   - Salida: `{"ok": bool, "files": list[Path], "count": int, "duration_s": float, "error": str | None}`

### 9.3 Gestión de Fallos y Verificación
- Verificación de imagen mediante apertura e inspección de cabecera con PIL y tamaño mínimo > 4KB.
- Si el servidor reporta `Not signed in to Google`, se mapea a excepción `FlowMCPAuthError` y no se reintenta, pasando inmediatamente al siguiente plan.
- Timeout estricto de 120s por generación; en caso de timeout se aborta el proceso sin dejar locks residuales.

---

## 10. Implementación y Validación del Puente (2026-10-20)
- **Módulo Cliente:** [`backend/services/flow_mcp_client.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/services/flow_mcp_client.py) implementa handshake secuencial Stdio JSON-RPC 2.0 (`initialize` $\rightarrow$ `notifications/initialized` $\rightarrow$ `tools/call`), gestión de procesos con recolección de stderr y finalización garantizada.
- **Configuración:** [`backend/config.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/config.py) añade `FLOW_MCP_ENABLED` (False por defecto), `FLOW_MCP_DIR`, `FLOW_MCP_MODEL` y `FLOW_MCP_TIMEOUT`.
- **Integración de Pipeline:** [`backend/pipeline/images.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/backend/pipeline/images.py) añade el Plan 0 condicional `flow_mcp`, con verificación previa de imagen y copia segura hacia la ruta definitiva de escena.
- **Batería de Pruebas:** [`tests/test_flow_mcp_bridge.py`](file:///d:/PROYECTOS/YOUTUBE%20AUTOMATION/tests/test_flow_mcp_bridge.py) aprobada al 100% (**21/21 tests OK** en 0.70s), cubriendo flags, fallbacks, respuestas corruptas, timeouts y preservación de F5.1.
