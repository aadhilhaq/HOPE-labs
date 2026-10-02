/* HOPE Labs: the catalogue, the tool shown inside the shell, and the results across every tool.
   The page talks only to the launcher running on this computer; the launcher holds the one SSH
   connection and starts a tool on the login node when a card asks it to. */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

async function api(path, body) {
  const url = path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN);
  const init = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const answer = await fetch(url, init);
  let data = {};
  try { data = await answer.json(); } catch (e) { data = { error: "the launcher sent something unreadable (" + answer.status + ")" }; }
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

/* ------------------------------------------------------------------ state */
let STATE = { tools: [], categories: [] };
let VIEW = "tools";          // tools | runs | a tool key
let CATEGORY = "";
let QUERY = "";
let RUNFILTER = "";

const byKey = (key) => STATE.tools.find((t) => t.key === key);

/* the mark on each card: one glyph per kind of work, drawn rather than fetched */
const GLYPH = {
  adcp: '<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2.4" fill="currentColor"/>',
  aptamer: '<path d="M7 4 C17 8, 7 16, 17 20 M17 4 C7 8, 17 16, 7 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  bindcraft: '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 12 L12 6 L18 12 L12 18 Z" fill="none" stroke="currentColor" stroke-width="2"/>',
  pipelines: '<path d="M4 7h16 M4 12h10 M4 17h13" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  hopemd: '<path d="M4 16 L8 7 L12 14 L16 9 L20 13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
};

function glyph(key, size) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size || 21);
  svg.setAttribute("height", size || 21);
  svg.innerHTML = GLYPH[key] || GLYPH.hopemd;
  return svg;
}

/* ------------------------------------------------------------------ the rail */
function paintRail() {
  const box = $("railtools");
  box.innerHTML = "";
  STATE.tools.forEach((tool) => {
    const row = el("button", "ritem");
    row.appendChild(el("span", "dot" + (tool.running ? " up" : "")));
    row.appendChild(el("span", "nm", tool.name));
    row.title = tool.running ? tool.name + " is running" : "start " + tool.name;
    row.onclick = () => open_tool(tool.key);
    box.appendChild(row);
  });
  document.querySelectorAll(".ritem[data-view]").forEach((b) => {
    b.classList.toggle("on", VIEW === b.dataset.view);
    b.onclick = () => show(b.dataset.view);
  });
}

/* ------------------------------------------------------------------ the catalogue */
function card(tool) {
  const box = el("div", "tool");
  const head = el("div", "head");
  const badge = el("div", "badge");
  badge.appendChild(glyph(tool.key));
  head.appendChild(badge);
  const titles = el("div");
  const h = el("h3");
  h.appendChild(document.createTextNode(tool.name));
  h.appendChild(el("span", "state" + (tool.running ? " up" : ""), tool.running ? "running" : tool.category));
  titles.appendChild(h);
  titles.appendChild(el("div", "tag", tool.tagline));
  head.appendChild(titles);
  box.appendChild(head);
  box.appendChild(el("div", "blurb", tool.blurb));

  if (tool.takes || tool.gives) {
    // each label stays with its value: "leaves" at the end of one line and what it leaves on the
    // next reads as two separate things
    const chain = el("div", "chain");
    [["takes", tool.takes], ["leaves", tool.gives]].forEach(([word, what]) => {
      if (!what) return;
      const pair = el("span", "pair");
      pair.appendChild(document.createTextNode(word + " "));
      pair.appendChild(el("b", null, what));
      chain.appendChild(pair);
    });
    box.appendChild(chain);
  }

  const acts = el("div", "acts");
  const go = el("button", "btn pri", tool.running ? "Open" : "Launch");
  go.onclick = () => open_tool(tool.key, go);
  acts.appendChild(go);
  if (tool.running) {
    const stop = el("button", "btn sm", "Stop");
    stop.onclick = async (e) => { e.stopPropagation(); await stop_tool(tool.key); };
    acts.appendChild(stop);
  }
  tool.next_steps.forEach((step) => {
    const to = byKey(step.to);
    if (!to) return;
    const next = el("button", "btn sm next", "→ " + to.name);
    next.title = step.label;
    next.onclick = (e) => { e.stopPropagation(); open_tool(step.to); };
    acts.appendChild(next);
  });
  box.appendChild(acts);
  return box;
}

function paintTools() {
  const grid = $("grid");
  grid.innerHTML = "";
  const q = QUERY.trim().toLowerCase();
  const shown = STATE.tools.filter((t) =>
    (!CATEGORY || t.category === CATEGORY) &&
    (!q || (t.name + " " + t.tagline + " " + t.blurb + " " + t.category).toLowerCase().includes(q)));
  shown.forEach((tool) => grid.appendChild(card(tool)));
  if (!shown.length) grid.appendChild(el("p", "empty", "No tool matches that."));
  $("toolcount").textContent = shown.length + " of " + STATE.tools.length
    + " · " + STATE.tools.filter((t) => t.running).length + " running";

  const cats = $("cats");
  cats.innerHTML = "";
  const all = el("button", "chip" + (CATEGORY ? "" : " on"), "All");
  all.onclick = () => { CATEGORY = ""; paintTools(); };
  cats.appendChild(all);
  STATE.categories.forEach((name) => {
    const chip = el("button", "chip" + (CATEGORY === name ? " on" : ""), name);
    chip.onclick = () => { CATEGORY = CATEGORY === name ? "" : name; paintTools(); };
    cats.appendChild(chip);
  });
}

/* ------------------------------------------------------------------ views */
function show(view) {
  VIEW = view;
  $("view-tools").hidden = view !== "tools";
  $("view-runs").hidden = view !== "runs";
  ["view-tools", "view-runs"].forEach((id) => { $(id).style.display = $(id).hidden ? "none" : "flex"; });
  if (view === "runs") loadRuns();
  paintRail();
}

/* Each tool opens in a window of its own, served by the launcher: the tool's own page with a bar
   across the top that reaches the others. The window is named after the tool, so picking the same
   one again raises the window already open instead of starting a second copy. */
function openWindow(key, from) {
  const url = "/tool?key=" + encodeURIComponent(key) + "&t=" + encodeURIComponent(TOKEN)
            + (from ? "&from=" + encodeURIComponent(from) : "");
  const win = window.open(url, "hopelabs-" + key, "width=1480,height=940");
  if (!win) flash("Chrome blocked the window. Click Pop-up blocked at the right of the address bar, choose Always allow, then pick the tool again.", true);
  else win.focus();
}

/* Open the tool's window inside the click, before anything is awaited. Chrome lets a page open a
   window only while the click that asked for it is fresh (about five seconds), and starting a tool
   on the cluster takes far longer than that. So the window opens at once and starts the tool
   itself, showing its progress where the person is looking. `from` is a run folder to hand over:
   the tool's window shows it with a Copy button. */
function open_tool(key, button, from) {
  const tool = byKey(key);
  if (!tool) return;
  openWindow(key, from);
  if (!tool.running && button) {
    const was = button.textContent;
    button.disabled = true;
    button.textContent = "starting…";
    setTimeout(() => { button.disabled = false; button.textContent = was; }, 4000);
  }
  // the window starts the tool; read the state back so this block says "running" when it is
  setTimeout(() => { refresh().catch(() => {}); }, 3000);
  setTimeout(() => { refresh().catch(() => {}); }, 20000);
}

async function stop_tool(key) {
  try {
    const got = await api("/api/stop", { tool: key });
    Object.assign(byKey(key) || {}, got);
    flash((got.name || "the tool") + " stopped.");
    paintTools(); paintRail();
  } catch (failure) { flash(failure.message, true); }
}


/* ------------------------------------------------------------------ results */
function when(seconds) {
  if (!seconds) return "";
  const gap = Date.now() / 1000 - seconds;
  if (gap < 3600) return Math.max(1, Math.round(gap / 60)) + " min ago";
  if (gap < 86400) return Math.round(gap / 3600) + " h ago";
  if (gap < 86400 * 14) return Math.round(gap / 86400) + " days ago";
  return new Date(seconds * 1000).toISOString().slice(0, 10);
}

async function loadRuns(refresh) {
  const body = $("runbody");
  body.innerHTML = "";
  body.appendChild(el("p", "empty", "Reading the run folders…"));
  let runs = [];
  try { runs = (await api("/api/runs" + (refresh ? "?refresh=1" : ""))).runs; }
  catch (failure) { body.innerHTML = ""; body.appendChild(el("p", "empty", failure.message)); return; }

  const filter = $("runfilter");
  filter.innerHTML = "";
  const all = el("button", "chip" + (RUNFILTER ? "" : " on"), "All tools");
  all.onclick = () => { RUNFILTER = ""; loadRuns(); };
  filter.appendChild(all);
  STATE.tools.forEach((tool) => {
    const n = runs.filter((r) => r.tool === tool.key).length;
    if (!n) return;
    const chip = el("button", "chip" + (RUNFILTER === tool.key ? " on" : ""), tool.name + " " + n);
    chip.onclick = () => { RUNFILTER = RUNFILTER === tool.key ? "" : tool.key; loadRuns(); };
    filter.appendChild(chip);
  });

  const shown = runs.filter((r) => !RUNFILTER || r.tool === RUNFILTER);
  body.innerHTML = "";
  if (!shown.length) {
    body.appendChild(el("p", "empty", "No run folders yet. Launch a tool, submit something, and its runs appear here."));
    return;
  }
  const table = el("table", "runs");
  const head = el("tr");
  ["Run", "Tool", "When", "Next step"].forEach((h) => head.appendChild(el("th", null, h)));
  table.appendChild(el("thead")).appendChild(head);
  const tbody = el("tbody");
  shown.forEach((run) => {
    const tr = el("tr");
    const first = el("td");
    first.appendChild(el("div", "runname", run.name));
    first.appendChild(el("div", "runpath", run.path));
    tr.appendChild(first);
    const second = el("td");
    second.appendChild(el("span", "toolchip", run.tool_name));
    tr.appendChild(second);
    tr.appendChild(el("td", null, when(run.when)));
    // The hand-off, beside the run it applies to: the path goes on the clipboard and the tool
    // that takes it opens, because the tools' own pages cannot yet be opened on a given folder.
    const last = el("td");
    const acts = el("div", "acts");
    run.next_steps.forEach((step) => {
      const to = byKey(step.to);
      if (!to) return;
      const b = el("button", "btn sm next", step.label);
      b.onclick = () => open_tool(step.to, b, run.path);
      acts.appendChild(b);
    });
    if (!run.next_steps.length) acts.appendChild(el("span", "why", "—"));
    last.appendChild(acts);
    tr.appendChild(last);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  body.appendChild(table);
}

/* ------------------------------------------------------------------ start */
async function refresh() {
  const got = await api("/api/state");
  STATE = got;
  $("who").textContent = (got.user || "") + " · " + (got.host || "grace");
  paintTools();
  paintRail();
}

$("q").addEventListener("input", (e) => { QUERY = e.target.value; paintTools(); });
$("runrefresh").onclick = () => loadRuns(true);

(async function start() {
  if (!TOKEN) { flash("Open this page from the launcher window: it carries the token that gates it.", true); return; }
  try { await refresh(); } catch (failure) { flash(failure.message, true); }
  // The tools are started and stopped from here, but a tool can also die on its own; this keeps
  // the rail honest without getting in the way.
  setInterval(() => { refresh().catch(() => {}); }, 15000);
})();
