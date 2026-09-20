// popup de la extensión YT Automation v2.0
const $ = s => document.querySelector(s);

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "GET_BACKEND" }, ({ backend }) => {
    fetch(`${backend}/api/extension/pending`)
      .then(r => r.json())
      .then(d => { $("#status").textContent = `✅ Backend conectado · ${d.pending} imágenes en cola`; })
      .catch(() => { $("#status").textContent = "⚠️ Backend no responde en " + backend; });
  });
}

chrome.storage.local.get(["projectId", "auto"], ({ projectId, auto }) => {
  $("#project").value = projectId || "";
  $("#auto").classList.toggle("on", !!auto);
});

$("#auto").onclick = () => $("#auto").classList.toggle("on");

$("#save").onclick = () => {
  chrome.storage.local.set({
    projectId: $("#project").value.trim(),
    auto: $("#auto").classList.contains("on"),
  }, refreshStatus);
};

refreshStatus();
