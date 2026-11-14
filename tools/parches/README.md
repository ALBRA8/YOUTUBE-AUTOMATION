# Parches de Servidores MCP Externos

Este directorio respalda los parches aplicados a dependencias o servidores MCP instalados de forma aislada fuera del repositorio (por ejemplo en entornos gestionados por `uv tool`).

## `notebooklm_mcp_api_client.py`

- **Ruta de origen en máquina local:**  
  `%APPDATA%\uv\tools\notebooklm-mcp-server\Lib\site-packages\notebooklm_mcp\api_client.py`
- **Motivo del parche:**  
  La versión oficial de `notebooklm-mcp-server` (v0.1.15) viene configurada con rutas y endpoints legacy que provocan errores HTTP 401 Unauthorized y listados vacíos `[LIST_EMPTY]` al interactuar con las APIs internas de Google NotebookLM. Al estar instalado dentro del entorno global de `uv`, cualquier reinstalación o actualización del paquete sobrescribiría estas correcciones. Este archivo permite restaurar el parche inmediatamente copiándolo a la ruta del site-packages de `uv`.
- **Fragilidad conocida y mantenimiento:**  
  - **Etiqueta de Build (`NOTEBOOKLM_BL`):** Utiliza la etiqueta de build `20261112.11`. Google actualiza esta versión periódicamente cada pocas semanas. Si la versión cambia en los servidores de Google, el síntoma será nuevamente un listado vacío de notebooks (`[LIST_EMPTY]`). Si esto ocurre, debe inspeccionarse la petición batchexecute en la pestaña Network de Chrome y actualizar el valor de `bl` en este archivo o en la variable de entorno correspondiente.
