// YT Automation v2.0 — content script para Google Labs / ImageFX
// Detecta las imágenes generadas y añade un botón "➤ Enviar" sobre cada una.
// Modo AUTO: envía cada imagen nueva sin clic (configurable en el popup).
(() => {
  let autoMode = false;
  const seen = new WeakSet();
  let observer = null;

  chrome.storage.local.get(["auto"], ({ auto }) => { autoMode = !!auto; start(); });
  chrome.storage.onChanged.addListener(ch => {
    if (ch.auto) { autoMode = !!ch.auto.newValue; autoMode ? start() : stop(); }
  });

  function isGenerated(img) {
    // heurística: imágenes de resultados de ImageFX (blob/data/https largas)
    return img && img.src && !img.closest("header,nav,footer") &&
           (img.naturalWidth >= 256 || img.width >= 256) &&
           /labs\.google|lh3\.googleusercontent|storage\.googleapis/.test(img.src);
  }

  function buttonFor(img) {
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:absolute;top:8px;right:8px;z-index:99999;display:flex;gap:6px;";
    const btn = document.createElement("button");
    btn.textContent = "➤ Enviar";
    btn.title = "Enviar a YT Automation (Plan B)";
    btn.style.cssText = `padding:6px 12px;border-radius:9px;border:none;cursor:pointer;
      font:700 12px system-ui;background:#7c5cff;color:#fff;box-shadow:0 4px 14px rgba(0,0,0,.4);`;
    btn.onclick = e => { e.stopPropagation(); send(img.src, btn); };
    wrap.appendChild(btn);
    return wrap;
  }

  function decorate(img) {
    if (seen.has(img) || !isGenerated(img)) return;
    seen.add(img);
    const host = img.parentElement;
    if (!host) return;
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.appendChild(buttonFor(img));
    if (autoMode) send(img.src, null);
  }

  function scan() { document.querySelectorAll("img").forEach(decorate); }

  function start() {
    if (observer) return;
    scan();
    observer = new MutationObserver(() => scan());
    observer.observe(document.body, { childList: true, subtree: true });
  }
  function stop() { observer?.disconnect(); observer = null; }

  function send(url, btn) {
    chrome.storage.local.get(["projectId"], ({ projectId }) => {
      chrome.runtime.sendMessage({ type: "SEND_IMAGE", url, projectId }, res => {
        if (btn) {
          btn.textContent = res?.ok ? "✓ Enviada" : "✗ Error";
          btn.style.background = res?.ok ? "#2bd976" : "#ff5470";
          setTimeout(() => { btn.textContent = "➤ Enviar"; btn.style.background = "#7c5cff"; }, 2200);
        }
      });
    });
  }
})();
