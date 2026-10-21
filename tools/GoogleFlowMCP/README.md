# srz-google-flow-mcp

Genera imágenes con **Google Flow** (Nano Banana Pro / 2 / 2 Lite) directamente desde
**Claude Code** o **Codex**, pidiéndolo con tus palabras. Usa tu propio Chrome con tu cuenta
de Google: abre Flow, escribe el prompt, genera y guarda las imágenes en tu ordenador.

También puede **subir fotos tuyas** (un producto, un avatar, un logo…) y usarlas como
referencia en el prompt.

Funciona en **Mac** y **Windows**.

## Qué necesitas

- **Claude Code** o **Codex** instalado
- **Google Chrome**
- Una **cuenta de Google** con acceso a Flow (https://flow.google.com)

(Node.js también hace falta, pero si no lo tienes tu Claude / Codex te ayuda a instalarlo.)

## Instalación (2 minutos)

1. **Descomprime** el zip donde quieras que se quede (por ejemplo en Documentos).
   No muevas la carpeta después de instalar.
2. **Abre Claude Code (o Codex) dentro de esta carpeta:**
   - Mac: abre la Terminal, escribe `cd ` (con espacio), arrastra la carpeta a la ventana y pulsa Enter. Luego escribe `claude` (o `codex`).
   - Windows: abre la carpeta, haz clic en la barra de direcciones, escribe `cmd` y pulsa Enter. Luego escribe `claude` (o `codex`).
   - Si usas la app de escritorio, simplemente abre esta carpeta como proyecto.
3. Escribe: **`instálalo`**

Tu Claude / Codex hace el resto: instala lo necesario, te pregunta **dónde quieres guardar
las imágenes**, lo conecta y abre una ventana de Chrome para que **inicies sesión en Google
Flow una sola vez**. Al final genera una imagen de prueba.

4. **Cierra y vuelve a abrir** Claude Code / Codex. Listo.

## Cómo se usa

Desde cualquier carpeta, pídeselo normal:

- *"Genera una imagen de un gato astronauta en formato 9:16"*
- *"Hazme 4 versiones con Nano Banana Pro de una taza de café sobre una mesa de madera"*
- *"Sube la foto `inputs/producto.jpg` como producto y genera una foto de ese producto en una cocina"*

Opciones que puedes pedir:

| Qué | Valores |
|---|---|
| Formato | `1:1` `16:9` `9:16` `4:3` `3:4` |
| Cantidad | de 1 a 4 imágenes |
| Modelo | Nano Banana **Pro**, Nano Banana **2** (por defecto), Nano Banana 2 **Lite** |

Las imágenes se guardan en la carpeta que elegiste al instalar (para cambiarla, díselo a
tu Claude / Codex o edita `config.json`).

## Fotos de referencia

Cuando subes una foto le das un nombre (por ejemplo `producto`) y en el prompt escribes
`@{producto}` donde quieras usarla. Tu Claude / Codex lo hace por ti si se lo pides con
palabras. Tienes un ejemplo en `examples/referencia-producto.txt`.

## Actualizar a una versión nueva

1. Descarga el zip nuevo desde srzclub.com/flow-mcp.
2. Abre Claude Code (o Codex) en la carpeta donde lo instalaste y escribe: **`actualízalo`**.

Tu IA copia los archivos nuevos y mantiene tu configuración, tus imágenes y tu sesión.
Después, reinicia Claude Code / Codex.

## ¿Y ChatGPT?

La app de ChatGPT (y el navegador Atlas) no pueden usarlo: solo aceptan conectores en
internet, y esta herramienta tiene que funcionar en tu ordenador porque maneja tu Chrome.
**Codex sí funciona.**

## Avisos

- La ventana de Chrome que se abre es **independiente** de tu Chrome normal. Puedes
  cerrarla cuando termines; se vuelve a abrir sola cuando generas.
- Mientras esa ventana está abierta, otros programas de tu ordenador podrían controlarla
  (solo desde tu propio equipo). Ciérrala cuando no la uses.
- Es una automatización **no oficial** de la web de Flow. Si Google cambia la página,
  puede dejar de funcionar hasta que se actualice.
- Lo que consuma cada imagen depende de tu cuenta y tu plan de Google Flow.

## Para usuarios avanzados (terminal)

```bash
node src/cli.js chrome                                   # abrir el Chrome de Flow
node src/cli.js "prompt" --aspect 9:16 --count 2 --model pro
node src/cli.js --prompt-file prompt.txt
node src/cli.js upload inputs/foto.jpg --name avatar
node src/cli.js assets                                   # listar fotos del proyecto
node src/cli.js project new | project show | project set <id>
```

Variables de entorno opcionales: `FLOW_CHROME_PATH` (ruta de Chrome), `FLOW_OUTPUT_DIR`
(carpeta de imágenes), `FLOW_USER_DATA_DIR` (perfil del Chrome de Flow), `FLOW_CDP_PORT`
(puerto, por defecto `9333`), `FLOW_PROJECT_ID` (proyecto de Flow concreto).

Licencia MIT.
