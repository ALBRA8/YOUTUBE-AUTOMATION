"""
YOUTUBE AUTOMATION v2.0 — Cliente del Servidor GoogleFlowMCP
Comunica el orquestador audiovisual con tools/GoogleFlowMCP/src/mcp.js vía Stdio JSON-RPC 2.0.
Soporta handshake secuencial, gestión robusta de procesos hijos, parsing de respuestas
reales y degradación controlada ante fallos.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import config

log = logging.getLogger("flow_mcp")

# ── Excepciones tipadas ────────────────────────────────────────────────────────
class FlowMCPError(Exception):
    """Error base de comunicación o ejecución con GoogleFlowMCP."""


class FlowMCPAuthError(FlowMCPError):
    """Error de sesión: Chrome en FlowImageChrome no está autenticado en Google."""


class FlowMCPTimeoutError(FlowMCPError):
    """La operación en GoogleFlowMCP superó el tiempo límite configurado."""


class FlowMCPResponseError(FlowMCPError):
    """Respuesta vacía o malformada del servidor MCP."""


# ── Detección de binarios y disponibilidad ─────────────────────────────────────
def get_node_bin() -> str | None:
    """Localiza el binario de Node.js en el sistema."""
    which_bin = shutil.which("node")
    if which_bin:
        return which_bin
    standard_windows = Path("C:\\Program Files\\nodejs\\node.exe")
    if standard_windows.is_file():
        return str(standard_windows)
    return None


def available() -> bool:
    """Indica si el proveedor GoogleFlowMCP está habilitado y disponible localmente."""
    if not getattr(config, "FLOW_MCP_ENABLED", False):
        return False
    entry = getattr(config, "FLOW_MCP_DIR", Path(".")) / "src" / "mcp.js"
    if not entry.is_file():
        return False
    return get_node_bin() is not None


# ── Validación de binarios de imagen generados ─────────────────────────────────
def verify_image_file(path: Path, min_bytes: int = 4096) -> bool:
    """Verifica que el archivo exista en disco, tenga un tamaño razonable y sea una imagen válida."""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
        if size < min_bytes:
            return False

        # Validación de cabecera mágica (PNG, JPEG, WEBP)
        with open(path, "rb") as f:
            header = f.read(16)
        is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpeg = header.startswith(b"\xff\xd8\xff")
        is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if not (is_png or is_jpeg or is_webp):
            return False

        # Si PIL está instalado en el entorno, realizar verificación profunda del formato
        try:
            from PIL import Image

            with Image.open(path) as img:
                img.verify()
        except ImportError:
            pass  # Cabecera mágica y tamaño válidos son suficientes si PIL no está instalado
        except Exception:
            return False

        return True
    except Exception as e:
        log.debug("Verificación de imagen falló para %s: %s", path, e)
        return False


def parse_image_paths_from_text(text: str, verify: bool = True) -> list[Path]:
    """
    Normaliza y extrae las rutas reales de imagen devueltas por flow_generate_image.
    Formato real emitido por tools/GoogleFlowMCP/src/mcp.js:
      Generated N image(s) in Xs with MODEL (ASPECT):\\npath1\\npath2
    """
    if not text or not isinstance(text, str):
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    candidates: list[str] = []
    # Si contiene la cabecera canónica "Generated ...:\n"
    if ":\n" in text:
        _, _, body = text.partition(":\n")
        candidates = [line.strip() for line in body.splitlines() if line.strip()]
    else:
        # Fallback: descartar líneas de cabecera que comiencen por 'Generated '
        for line in lines:
            if line.startswith("Generated ") and ("image(s)" in line or "with " in line):
                continue
            candidates.append(line)

    results: list[Path] = []
    for cand in candidates:
        cand_clean = cand.strip().strip("'\"")
        if not cand_clean:
            continue
        p = Path(cand_clean)
        if verify:
            if verify_image_file(p):
                results.append(p)
            else:
                log.warning("Ruta candidata descartada por validación de imagen: %s", p)
        else:
            results.append(p)

    return results


# ── Ciclo de vida del subproceso MCP Stdio ─────────────────────────────────────
async def _read_jsonrpc_message(proc: asyncio.subprocess.Process, timeout: float) -> dict[str, Any]:
    """Lee una línea de stdout y la deserializa como JSON-RPC ignorando líneas en blanco."""
    while True:
        line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        if not line_bytes:
            raise FlowMCPResponseError("El servidor MCP cerró stdout inesperadamente.")
        line_str = line_bytes.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue
        try:
            return json.loads(line_str)
        except json.JSONDecodeError:
            log.debug("Ignorando salida no-JSON de stdout: %s", line_str)
            continue


async def call_tool(
    tool_name: str,
    arguments: dict[str, Any],
    timeout: float | None = None,
    cwd: Path | None = None,
) -> str:
    """
    Ejecuta una herramienta en el servidor MCP vía Stdio con handshake JSON-RPC completo.
    Garantiza terminación limpia de procesos, drenaje de buffers y captura de errores.
    """
    if not available():
        raise FlowMCPError("GoogleFlowMCP no está habilitado o no se encuentra disponible.")

    node_bin = get_node_bin()
    if not node_bin:
        raise FlowMCPError("Binario 'node' no encontrado en el sistema.")

    entry_script = getattr(config, "FLOW_MCP_DIR", Path(".")) / "src" / "mcp.js"
    op_timeout = timeout if timeout is not None else getattr(config, "FLOW_MCP_TIMEOUT", 120.0)
    work_dir = cwd or getattr(config, "FLOW_MCP_DIR", Path("."))

    stderr_chunks: list[bytes] = []

    async def _drain_stderr(stream: asyncio.StreamReader):
        try:
            while True:
                chunk = await stream.read(1024)
                if not chunk:
                    break
                stderr_chunks.append(chunk)
        except Exception:
            pass

    proc = await asyncio.create_subprocess_exec(
        node_bin,
        str(entry_script),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_dir),
    )

    stderr_task = asyncio.create_task(_drain_stderr(proc.stderr))

    try:
        # 1. Handshake: initialize request (id: 1)
        init_id = 1
        init_payload = {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "yta-flow-bridge", "version": "2.0.0"},
            },
        }
        init_bytes = (json.dumps(init_payload) + "\n").encode("utf-8")
        proc.stdin.write(init_bytes)
        await proc.stdin.drain()

        # Esperar respuesta initialize (máx 30s)
        init_resp = await _read_jsonrpc_message(proc, timeout=min(op_timeout, 30.0))
        if init_resp.get("id") != init_id or "result" not in init_resp:
            raise FlowMCPResponseError(f"Handshake initialize inválido: {init_resp}")

        # 2. Handshake: notifications/initialized
        notif_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        notif_bytes = (json.dumps(notif_payload) + "\n").encode("utf-8")
        proc.stdin.write(notif_bytes)
        await proc.stdin.drain()

        # 3. Invocar herramienta: tools/call (id: 2)
        call_id = 2
        call_payload = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        call_bytes = (json.dumps(call_payload) + "\n").encode("utf-8")
        proc.stdin.write(call_bytes)
        await proc.stdin.drain()

        # Esperar respuesta de la herramienta
        call_resp = await _read_jsonrpc_message(proc, timeout=op_timeout)
        if call_resp.get("id") != call_id:
            raise FlowMCPResponseError(f"ID de respuesta inesperado ({call_resp.get('id')} != {call_id})")

        if "error" in call_resp:
            err_data = call_resp["error"]
            err_msg = err_data.get("message", str(err_data)) if isinstance(err_data, dict) else str(err_data)
            raise FlowMCPError(f"Error JSON-RPC: {err_msg}")

        result = call_resp.get("result", {})
        if result.get("isError"):
            content = result.get("content", [])
            err_text = content[0].get("text", "Error reportado por herramienta") if content else "Error reportado"
            if "Not signed in" in err_text:
                raise FlowMCPAuthError(err_text)
            raise FlowMCPError(err_text)

        content = result.get("content", [])
        if not content:
            raise FlowMCPResponseError("Respuesta de herramienta vacía (sin content).")

        return content[0].get("text", "")

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise FlowMCPTimeoutError(f"Timeout de {op_timeout}s esperando respuesta de {tool_name}")
    except Exception as e:
        stderr_log = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
        if stderr_log:
            log.warning("GoogleFlowMCP stderr durante %s: %s", tool_name, stderr_log)
        raise
    finally:
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                proc.kill()
        except Exception:
            pass
        stderr_task.cancel()


# ── Funciones de Alto Nivel ───────────────────────────────────────────────────
async def generate_image(
    prompt: str,
    aspect: str = "1:1",
    count: int = 1,
    model: str | None = None,
    out_dir: Path | None = None,
    timeout: float | None = None,
) -> list[Path]:
    """
    Genera imágenes con Nano Banana mediante flow_generate_image.
    Devuelve lista de Paths locales verificados en disco.
    """
    target_aspect = aspect if aspect in ("16:9", "4:3", "1:1", "3:4", "9:16") else "1:1"
    target_model = model or getattr(config, "FLOW_MCP_MODEL", "2") or "2"
    target_count = max(1, min(int(count), 4))

    arguments: dict[str, Any] = {
        "prompt": prompt,
        "aspect": target_aspect,
        "count": target_count,
        "model": target_model,
    }
    if out_dir:
        arguments["outDir"] = str(Path(out_dir).resolve())

    raw_text = await call_tool("flow_generate_image", arguments, timeout=timeout)
    return parse_image_paths_from_text(raw_text, verify=True)


async def upload_file(
    file_path: Path,
    name: str | None = None,
    replace: bool = False,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Sube un archivo de imagen al proyecto de Flow y registra su etiqueta @name."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Archivo a subir no encontrado: {p}")

    arguments: dict[str, Any] = {
        "filePath": str(p),
        "replace": bool(replace),
    }
    if name:
        arguments["name"] = name.strip()

    raw_text = await call_tool("flow_upload_file", arguments, timeout=timeout)
    return {"ok": True, "raw": raw_text}


async def list_assets(timeout: float = 30.0) -> list[str]:
    """Lista los nombres de los activos presentes en el proyecto activo de Flow."""
    raw_text = await call_tool("flow_list_assets", {}, timeout=timeout)
    if "has no images yet" in raw_text:
        return []
    assets: list[str] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            assets.append(line[2:].strip())
        elif line:
            assets.append(line)
    return assets


async def new_project(timeout: float = 30.0) -> str:
    """Crea un nuevo proyecto en Google Flow y devuelve su identificador."""
    raw_text = await call_tool("flow_new_project", {}, timeout=timeout)
    return raw_text.strip()
