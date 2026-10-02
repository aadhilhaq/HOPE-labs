/* One tool in a window of its own: the tool's page, with a bar across the top that reaches every
   other tool. The bar is served by the launcher, so the tool below it is untouched. */
"use strict";

const Q = new URLSearchParams(location.search);
const TOKEN = Q.get("t") || "";
const KEY = Q.get("key") || "";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

async function api(path, body) {
  const url = path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN);
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const answer = await fetch(url, init);
  let data = {};
  try { data = await answer.json(); } catch (e) { data = { error: "the launcher sent something unreadable" }; }
  if (!answer.ok) throw new Error(data.error || "the launcher answered " + answer.status);
  return data;
}

let flashTimer = 0;
function flash(text, bad) {
  clearTimeout(flashTimer);
  document.querySelectorAll(".flash").forEach((n) => n.remove());
  const box = el("div", "flash" + (bad ? " bad" : ""), text);
  document.body.appendChild(box);
  flashTimer = setTimeout(() => box.remove(), bad ? 16000 : 7000);
}

/* A tool gets one window, named after it: asking for it again raises the window that is already
   open rather than starting a second copy. */
function openTool(key) {
  window.open("/tool?key=" + encodeURIComponent(key) + "&t=" + encodeURIComponent(TOKEN),
              "hopelabs-" + key, "width=1480,height=940");
}

async function paint() {
  const state = await api("/api/state");
  const tool = state.tools.find((t) => t.key === KEY);
  if (!tool) { document.title = "HOPE Labs"; flash("There is no tool called " + KEY + ".", true); return; }
  document.title = tool.name + " · HOPE Labs";
  $("t-name").textContent = tool.name;
  $("t-tag").textContent = tool.tagline;
  $("t-plain").href = tool.url || "#";

  const jump = $("t-jump");
  jump.innerHTML = "";
  state.tools.filter((t) => t.key !== KEY).forEach((other) => {
    const step = tool.next_steps.find((s) => s.to === other.key);
    const b = el("button", "btn sm" + (step ? " next" : ""), (step ? "→ " : "") + other.name);
    b.title = step ? step.label : "open " + other.name + " in its own window";
    b.onclick = async () => {
      if (!other.running) {
        b.disabled = true;
        const was = b.textContent;
        b.textContent = "starting…";
        try { await api("/api/launch", { tool: other.key }); }
        catch (failure) { flash(failure.message, true); b.disabled = false; b.textContent = was; return; }
        b.disabled = false;
        b.textContent = was;
      }
      openTool(other.key);
    };
    jump.appendChild(b);
  });

  if (!tool.running) {
    flash(tool.name + " is not running. Starting it…");
    try { Object.assign(tool, await api("/api/launch", { tool: KEY })); }
    catch (failure) { flash(failure.message, true); return; }
  }
  const frame = $("t-frame");
  if (frame.dataset.url !== tool.url) { frame.src = tool.url; frame.dataset.url = tool.url; }
  $("t-plain").href = tool.url;
}

$("t-home").onclick = () => window.open("/?t=" + encodeURIComponent(TOKEN), "hopelabs-home");
$("t-stop").onclick = async () => {
  try { await api("/api/stop", { tool: KEY }); flash("Stopped. You can close this window."); }
  catch (failure) { flash(failure.message, true); }
};

paint().catch((failure) => flash(failure.message, true));
