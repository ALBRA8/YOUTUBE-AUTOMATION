// YT Automation v2.0 — service worker: envía imágenes capturadas al backend
const DEFAULT_BACKEND = "http://127.0.0.1:8000";

async function getCfg() {
  const { backend } = await chrome.storage.local.get("backend");
  return { backend: backend || DEFAULT_BACKEND };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SEND_IMAGE") {
    (async () => {
      const { backend } = await getCfg();
      try {
        const res = await fetch(`${backend}/api/extension/images`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: msg.url,
            project_id: msg.projectId || null,
            source: "imagefx",
          }),
        });
        const data = await res.json();
        if (res.ok) {
          chrome.action.setBadgeText({ text: "✓" });
          setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
          sendResponse({ ok: true, id: data.id });
        } else {
          sendResponse({ ok: false, error: data.detail || res.statusText });
        }
      } catch (e) {
        sendResponse({ ok: false, error: "¿Backend encendido en 127.0.0.1:8000?" });
      }
    })();
    return true; // async
  }
  if (msg.type === "GET_BACKEND") {
    getCfg().then(c => sendResponse(c));
    return true;
  }
});
