/* HOPE Labs: the flow canvas. Cards are dropped from the palette, dragged into place and linked
   socket to socket; the target is filled in on the right; what is wrong with the flow is listed
   under it, and Launch is held shut until nothing is.

   The canvas decides nothing. Which links are legal, and what is wrong with a flow, come from the
   launcher, which reads the card catalogue the runner reads on the cluster. The refusals arrive as
   a table of every pair of sockets, worked out for the target as it is filled in at that moment,
   so a drag can colour the sockets without a round trip for each one, and a refusal reads here in
   the words the catalogue gives it rather than in a second set of our own.

   It shares api(), flash(), el() and $() with app.js, which is loaded before it. */
"use strict";

const CANVAS_MIN = [1180, 660];     // the drawing is this big at least, and the box scrolls

let CAT = null;                     // the catalogue, read once
let FLOW = blankFlow();             // exactly the document flow.py reads and writes
let REFUSALS = {};                  // "card:port>card:port" -> why not, or ""
let PROBLEMS = [];                  // check()'s sentences, as they came
let CHECKED = false;                // whether the launcher has answered about this flow yet
let PICKED = "";                    // the node whose settings the panel shows
let WIRE = null;                    // the link being drawn, while one is
let SAVED = [];                     // the flows kept on this computer
let checkSeq = 0;
let checkTimer = 0;

function blankFlow() { return { version: 1, name: "", runs_root: "", nodes: [], edges: [] }; }

const cardOf = (key) => (CAT ? CAT.cards.find((c) => c.key === key) : null);
const nodeOf = (id) => FLOW.nodes.find((n) => n.id === id);
const portOf = (card, side, key) => (card ? (card[side] || []).find((p) => p.key === key) : null);

/* The target has no tool of its own, so it has no glyph in app.js either: it is the one card that
   is a person's own input rather than something the lab installed. */
const TARGET_GLYPH = '<circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/>'
                   + '<path d="M12 2v5 M12 17v5 M2 12h5 M17 12h5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>';

function cardGlyph(card, size) {
  if (card.tool) return glyph(card.tool, size);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size || 18);
  svg.setAttribute("height", size || 18);
  svg.innerHTML = TARGET_GLYPH;
  return svg;
}

/* ------------------------------------------------------------------ the palette */
function paintPalette() {
  const box = $("palette");
  box.innerHTML = "";
  CAT.cards.forEach((card) => {
    const item = el("button", "pcard");
    const badge = el("span", "pbadge");
    badge.appendChild(cardGlyph(card));
    item.appendChild(badge);
    const names = el("span", "pnames");
    names.appendChild(el("span", "pname", card.name));
    names.appendChild(el("span", "ptagline", card.tagline));
    item.appendChild(names);
    item.title = "Put " + card.name + " on the canvas";
    item.draggable = true;
    item.ondragstart = (e) => e.dataTransfer.setData("text/plain", card.key);
    item.onclick = () => addCard(card.key);
    box.appendChild(item);
  });
}

/* ------------------------------------------------------------------ the flow */
function freeId(key) {
  if (!nodeOf(key)) return key;
  for (let n = 2; ; n++) {
    if (!nodeOf(key + "-" + n)) return key + "-" + n;
  }
}

function filledIn(card) {
  const out = {};
  (card.settings || []).forEach((s) => { out[s.key] = s.default === null ? "" : s.default; });
  return out;
}

function addCard(key, at) {
  const card = cardOf(key);
  if (!card) return "";
  const n = FLOW.nodes.length;
  const id = freeId(key);
  FLOW.nodes.push({ id: id, card: key, settings: filledIn(card),
                    at: at || [24 + (n % 4) * 252, 24 + Math.floor(n / 4) * 176] });
  PICKED = id;
  paint();
  check();
  return id;
}

function dropCard(id) {
  FLOW.nodes = FLOW.nodes.filter((n) => n.id !== id);
  FLOW.edges = FLOW.edges.filter((e) => e.from !== id && e.to !== id);
  if (PICKED === id) PICKED = (FLOW.nodes[0] || {}).id || "";
  paint();
  check();
}

function openFlow(doc) {
  FLOW = {
    version: 1, name: doc.name || "", runs_root: doc.runs_root || "",
    nodes: (doc.nodes || []).map((n) => ({ id: n.id, card: n.card,
                                           settings: Object.assign({}, n.settings),
                                           at: [(n.at || [24, 24])[0] || 0, (n.at || [24, 24])[1] || 0] })),
    edges: (doc.edges || []).map((e) => ({ from: e.from, fromPort: e.fromPort,
                                           to: e.to, toPort: e.toPort })),
  };
  $("flowname").value = FLOW.name;
  // the target first: it is the card a person reopening a flow is coming back to
  PICKED = ((FLOW.nodes.find((n) => n.card === "target") || FLOW.nodes[0] || {}).id) || "";
  paint();
  check();
}

/* ------------------------------------------------------------------ what may be linked */
/* The catalogue's answer, out of the table, with the three things the canvas itself knows: a card
   cannot feed itself, the same link cannot be drawn twice, and a socket not marked `many` holds
   one link. Those are about the drawing rather than about the tools, which is why they are worded
   here and everything else is not. */
function refusedLink(fromId, fromPort, toId, toPort) {
  const a = nodeOf(fromId), b = nodeOf(toId);
  if (!a || !b) return "that card is not on the canvas";
  if (a.id === b.id) return "a card cannot be linked to itself";
  if (FLOW.edges.some((e) => e.from === fromId && e.fromPort === fromPort
                          && e.to === toId && e.toPort === toPort)) return "that link is drawn already";
  const into = cardOf(b.card), port = portOf(into, "inputs", toPort);
  if (into && port && !port.many && FLOW.edges.some((e) => e.to === toId && e.toPort === toPort)) {
    return into.name + "'s " + port.label + " takes one link, and it has one already";
  }
  const why = REFUSALS[a.card + ":" + fromPort + ">" + b.card + ":" + toPort];
  return why === undefined ? "" : why;        // a card the table has never heard of: check() will say
}

function refusedEdge(e) {
  const a = nodeOf(e.from), b = nodeOf(e.to);
  if (!a || !b) return "";
  const why = REFUSALS[a.card + ":" + e.fromPort + ">" + b.card + ":" + e.toPort];
  return why === undefined ? "" : why;
}

/* ------------------------------------------------------------------ the drawing */
function paint() {
  const box = $("canvas");
  Array.prototype.slice.call(box.querySelectorAll(".node")).forEach((n) => n.remove());
  FLOW.nodes.forEach((node) => box.appendChild(nodeBox(node)));
  sizeCanvas();
  paintWires();
  paintPanel();
  paintProblems();
}

function socket(node, port, side) {
  const s = el("button", "sock");
  s.setAttribute("data-" + side, port.key);
  // the dot on the card's edge, then the label; the output column turns the pair round, so the
  // label stays beside what it carries and the dot stays on the outside
  s.appendChild(el("span", "dot" + (port.many ? " many" : "")));
  const text = el("span", "st");
  text.appendChild(el("span", "sl", port.label));
  // what it carries, where the label does not already say it
  const kinds = (port.kinds || []).filter((k) => port.label.indexOf(k) < 0);
  if (kinds.length) text.appendChild(el("span", "sk", kinds.join(" or ")));
  s.appendChild(text);
  s.dataset.tip = "carries " + (port.kinds || []).map((k) => CAT.kinds[k]).join("; or ")
                + (port.many ? ". Several links may arrive here." : "");
  s.title = s.dataset.tip;
  if (side === "out") {
    s.addEventListener("pointerdown", (e) => startWire(e, node, port));
  } else {
    // while a link is being drawn the socket takes the pointer, so the card does not move with it
    s.addEventListener("pointerdown", (e) => { if (WIRE) e.stopPropagation(); });
  }
  return s;
}

function nodeBox(node) {
  const card = cardOf(node.card);
  const box = el("div", "node" + (PICKED === node.id ? " on" : ""));
  box.dataset.node = node.id;
  box.style.left = Math.round(node.at[0] || 0) + "px";
  box.style.top = Math.round(node.at[1] || 0) + "px";
  const head = el("div", "nhead");
  const badge = el("span", "nbadge");
  if (card) badge.appendChild(cardGlyph(card));
  head.appendChild(badge);
  const names = el("span", "nnames");
  names.appendChild(el("span", "nname", card ? card.name : node.card));
  names.appendChild(el("span", "ntag", card ? card.tagline : "not a card this launcher knows"));
  head.appendChild(names);
  const off = el("button", "nx", "×");
  off.title = "Take " + (card ? card.name : node.card) + " off the canvas";
  off.onclick = (e) => { e.stopPropagation(); dropCard(node.id); };
  head.appendChild(off);
  box.appendChild(head);
  if (card) {
    const socks = el("div", "socks");
    const left = el("div", "col in"), right = el("div", "col out");
    (card.inputs || []).forEach((p) => left.appendChild(socket(node, p, "in")));
    (card.outputs || []).forEach((p) => right.appendChild(socket(node, p, "out")));
    socks.appendChild(left);
    socks.appendChild(right);
    box.appendChild(socks);
  }
  box.addEventListener("pointerdown", (e) => startMove(e, node, box));
  return box;
}

function sizeCanvas() {
  let w = CANVAS_MIN[0], h = CANVAS_MIN[1];
  FLOW.nodes.forEach((n) => {
    w = Math.max(w, Math.round(n.at[0] || 0) + 300);
    h = Math.max(h, Math.round(n.at[1] || 0) + 250);
  });
  const box = $("canvas");
  box.style.width = w + "px";
  box.style.height = h + "px";
}

function pointIn(e) {
  const c = $("canvas").getBoundingClientRect();
  return { x: e.clientX - c.left, y: e.clientY - c.top };
}

function socketAt(id, side, port) {
  const node = $("canvas").querySelector('.node[data-node="' + id + '"]');
  return node ? node.querySelector('.sock[data-' + side + '="' + port + '"] .dot') : null;
}

function where(id, side, port) {
  const dot = socketAt(id, side, port);
  if (!dot) return null;
  const c = $("canvas").getBoundingClientRect(), r = dot.getBoundingClientRect();
  return { x: r.left + r.width / 2 - c.left, y: r.top + r.height / 2 - c.top };
}

function curve(a, b) {
  const reach = Math.max(42, Math.abs(b.x - a.x) / 2);
  return "M" + a.x + " " + a.y + " C" + (a.x + reach) + " " + a.y
       + " " + (b.x - reach) + " " + b.y + " " + b.x + " " + b.y;
}

function wirePath(d, cls) {
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", d);
  p.setAttribute("class", cls);
  return p;
}

function paintWires() {
  const svg = $("wires");
  svg.innerHTML = "";
  FLOW.edges.forEach((edge, i) => {
    const a = where(edge.from, "out", edge.fromPort), b = where(edge.to, "in", edge.toPort);
    if (!a || !b) return;
    const why = refusedEdge(edge);
    const d = curve(a, b);
    // a wide invisible path over the thin one, so a link can be clicked off without aiming
    const hit = wirePath(d, "hit");
    hit.addEventListener("click", () => { FLOW.edges.splice(i, 1); paint(); check(); });
    const tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
    tip.textContent = why ? why + " - click to take this link out" : "click to take this link out";
    hit.appendChild(tip);
    svg.appendChild(hit);
    svg.appendChild(wirePath(d, "wire" + (why ? " bad" : "")));
  });
  if (WIRE) {
    const a = where(WIRE.from, "out", WIRE.port);
    if (a) svg.appendChild(wirePath(curve(a, { x: WIRE.x, y: WIRE.y }), "wire live"));
  }
}

/* ------------------------------------------------------------------ moving a card */
function pick(id) {
  PICKED = id;
  Array.prototype.slice.call($("canvas").querySelectorAll(".node"))
       .forEach((n) => n.classList.toggle("on", n.dataset.node === id));
  paintPanel();
}

function startMove(e, node, box) {
  if (WIRE || e.target.closest(".sock") || e.target.closest(".nx")) return;
  pick(node.id);
  const start = pointIn(e), at = [Math.round(node.at[0] || 0), Math.round(node.at[1] || 0)];
  const move = (ev) => {
    const now = pointIn(ev);
    node.at = [Math.max(0, Math.round(at[0] + now.x - start.x)),
               Math.max(0, Math.round(at[1] + now.y - start.y))];
    box.style.left = node.at[0] + "px";
    box.style.top = node.at[1] + "px";
    paintWires();
  };
  const up = () => {
    box.removeEventListener("pointermove", move);
    box.removeEventListener("pointerup", up);
    sizeCanvas();
    paintWires();
  };
  try { box.setPointerCapture(e.pointerId); } catch (ignore) { /* a mouse without capture */ }
  box.addEventListener("pointermove", move);
  box.addEventListener("pointerup", up);
  e.preventDefault();
}

/* ------------------------------------------------------------------ drawing a link */
/* Two ways round, because both are natural and one of them works with a trackpad on a knee: drag
   from an output socket to an input socket, or click the output socket and then the input one. */
function markSockets(hot) {
  Array.prototype.slice.call($("canvas").querySelectorAll(".sock[data-in]")).forEach((s) => {
    const id = s.closest(".node").dataset.node;
    s.classList.remove("ok", "no", "hot");
    s.title = s.dataset.tip;
    if (!WIRE) return;
    const why = refusedLink(WIRE.from, WIRE.port, id, s.getAttribute("data-in"));
    s.classList.add(why ? "no" : "ok");
    if (why) s.title = why;
    if (s === hot) s.classList.add("hot");
  });
  Array.prototype.slice.call($("canvas").querySelectorAll(".sock[data-out]")).forEach((s) => {
    const id = s.closest(".node").dataset.node;
    s.classList.toggle("from", !!WIRE && WIRE.from === id
                                     && WIRE.port === s.getAttribute("data-out"));
  });
}

function socketUnder(e) {
  const at = document.elementFromPoint(e.clientX, e.clientY);
  return at && at.closest ? at.closest(".sock[data-in]") : null;
}

function startWire(e, node, port) {
  e.preventDefault();
  e.stopPropagation();
  if (WIRE) return endWire();
  const a = where(node.id, "out", port.key) || { x: 0, y: 0 };
  WIRE = { from: node.id, port: port.key, x: a.x, y: a.y, moved: false, armed: false };
  document.addEventListener("pointermove", onWireMove);
  document.addEventListener("pointerup", onWireUp);
  markSockets();
  paintWires();
}

function onWireMove(e) {
  if (!WIRE) return;
  const at = pointIn(e);
  if (Math.abs(at.x - WIRE.x) + Math.abs(at.y - WIRE.y) > 3) WIRE.moved = true;
  WIRE.x = at.x;
  WIRE.y = at.y;
  markSockets(socketUnder(e));
  paintWires();
}

function onWireUp(e) {
  if (!WIRE) return;
  const sock = socketUnder(e);
  if (sock) return finishWire(sock);
  // a click rather than a drag: the link stays on the pointer until an input socket is clicked
  if (!WIRE.armed && !WIRE.moved) { WIRE.armed = true; return; }
  endWire();
}

function finishWire(sock) {
  const id = sock.closest(".node").dataset.node, port = sock.getAttribute("data-in");
  const why = refusedLink(WIRE.from, WIRE.port, id, port);
  if (why) {
    flash(why, true);
    endWire();
    return;
  }
  FLOW.edges.push({ from: WIRE.from, fromPort: WIRE.port, to: id, toPort: port });
  endWire();
  paint();
  check();
}

function endWire() {
  WIRE = null;
  document.removeEventListener("pointermove", onWireMove);
  document.removeEventListener("pointerup", onWireUp);
  markSockets();
  paintWires();
}

/* ------------------------------------------------------------------ the settings panel */
function field(node, setting) {
  const wrap = el("label", "field");
  const head = el("span", "flab", setting.label);
  if (setting.optional) head.appendChild(el("span", "opt", "optional"));
  wrap.appendChild(head);
  const put = (value) => { node.settings[setting.key] = value; touch(); };
  const held = node.settings[setting.key];
  let input;
  if (setting.kind === "choice") {
    input = el("select", "pick");
    const choices = (setting.choices || []).slice();
    // what a flow was saved with, even where the catalogue no longer offers it: the box has to
    // show what is stored, and check() is the one that says it is no longer a choice
    if (held != null && String(held) !== "" && choices.indexOf(String(held)) < 0) {
      choices.push(String(held));
    }
    choices.forEach((c) => {
      const o = el("option", null, c);
      o.value = c;
      input.appendChild(o);
    });
    input.value = held == null ? "" : String(held);
    input.onchange = () => put(input.value);
  } else if (setting.kind === "yesno") {
    input = el("input", "tick");
    input.type = "checkbox";
    input.checked = !!held;
    input.onchange = () => put(input.checked);
  } else if (setting.kind === "number") {
    input = el("input", "box num");
    input.type = "number";
    input.value = held == null ? "" : held;
    input.oninput = () => put(input.value === "" ? "" : Number(input.value));
  } else if (setting.kind === "range") {
    // A slider, between the two numbers the catalogue gives as its choices. No card asks for one
    // yet; it is drawn rather than left out so that the first one that does needs nothing here.
    const bounds = (setting.choices || []).map(Number);
    input = el("input", "slide");
    input.type = "range";
    input.min = bounds.length ? bounds[0] : 0;
    input.max = bounds.length > 1 ? bounds[1] : 100;
    input.value = held == null ? input.min : held;
    const read = el("span", "readout", String(input.value));
    input.oninput = () => { read.textContent = input.value; put(Number(input.value)); };
    wrap.appendChild(input);
    wrap.appendChild(read);
    if (setting.why) wrap.appendChild(el("span", "why2", setting.why));
    input.id = "set-" + setting.key;
    return wrap;
  } else {
    const mono = setting.kind === "residues" || setting.kind === "path";
    input = el("input", "box" + (mono ? " mono" : ""));
    input.type = "text";
    input.spellcheck = false;
    if (setting.kind === "path") input.placeholder = "a path on the cluster";
    if (setting.kind === "residues") input.placeholder = "54,56,66-70";
    input.value = held == null ? "" : String(held);
    input.oninput = () => put(input.value);
  }
  input.id = "set-" + setting.key;
  wrap.appendChild(input);
  if (setting.why) wrap.appendChild(el("span", "why2", setting.why));
  return wrap;
}

function paintPanel() {
  const box = $("panel");
  box.innerHTML = "";
  box.appendChild(el("div", "rlabel pl", "Settings"));
  const node = nodeOf(PICKED);
  if (!node) {
    box.appendChild(el("p", "phint", "Pick a card on the canvas to fill it in. In most flows the "
      + "target is the only card that needs anything: every other card takes the receptor and the "
      + "site through a link rather than asking again."));
    return;
  }
  const card = cardOf(node.card);
  box.appendChild(el("div", "ptitle", card ? card.name : node.card));
  box.appendChild(el("div", "ptag", card ? card.tagline : "not a card this launcher knows"));
  if (node.card === "target") {
    box.appendChild(el("p", "pnote", "The one card most flows need filling in. Everything linked "
      + "to it takes this receptor and these hotspots, so the design, the docking and the "
      + "simulation are all aimed at the same site."));
  }
  if (card && card.note) box.appendChild(el("p", "pnote", card.note));
  const settings = (card && card.settings) || [];
  if (card && !settings.length) {
    box.appendChild(el("p", "phint", card.name + " has nothing to fill in here: it works from the "
      + "target and from whatever arrives at its sockets."));
  }
  settings.forEach((s) => box.appendChild(field(node, s)));
  const off = el("button", "btn sm", "Take this card off");
  off.onclick = () => dropCard(node.id);
  box.appendChild(off);
}

/* ------------------------------------------------------------------ what is wrong with it */
function paintProblems() {
  const box = $("problems");
  box.innerHTML = "";
  if (!CHECKED) {
    box.appendChild(el("p", "pgood", "Checking…"));
  } else if (!PROBLEMS.length) {
    box.appendChild(el("p", "pgood", "Nothing wrong with this flow."));
  } else {
    const list = el("ul", "problist");
    PROBLEMS.forEach((why) => list.appendChild(el("li", null, why)));
    box.appendChild(list);
  }
  $("flowlaunch").disabled = !CHECKED || PROBLEMS.length > 0;
}

function touch() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(() => { check(); }, 250);
}

/* The launcher is asked about the flow as it stands, and answers with both the sentences and the
   table of what may reach what. So changing the binder length on the target re-reads every link
   already drawn: the ones that have become impossible are marked where they are, and said in the
   list under the canvas. */
async function check() {
  clearTimeout(checkTimer);
  FLOW.name = $("flowname").value.trim();
  const mine = ++checkSeq;
  let got;
  try {
    got = await api("/api/flow/check", { flow: FLOW });
  } catch (failure) {
    if (mine !== checkSeq) return;
    CHECKED = true;
    PROBLEMS = [failure.message];
    paintProblems();
    return;
  }
  if (mine !== checkSeq) return;                // a later check has already answered
  REFUSALS = got.refusals || {};
  PROBLEMS = got.problems || [];
  CHECKED = true;
  paintProblems();
  paintWires();
  markSockets();
}

/* ------------------------------------------------------------------ the flows kept here */
function paintSaved() {
  const pick = $("flowsaved");
  pick.innerHTML = "";
  const first = el("option", null, SAVED.length ? "Open a saved flow…" : "No saved flows yet");
  first.value = "";
  pick.appendChild(first);
  SAVED.forEach((f) => {
    const o = el("option", null, f.name);
    o.value = f.name;
    pick.appendChild(o);
  });
  pick.value = "";
  $("flowforget").disabled = !SAVED.some((f) => f.name === FLOW.name);
}

async function loadSaved() {
  try { SAVED = (await api("/api/flow/saved")).flows || []; } catch (failure) { SAVED = []; }
  paintSaved();
}

/* ------------------------------------------------------------------ the view */
async function openFlows() {
  if (!CAT) {
    try {
      CAT = await api("/api/flow/cards");
    } catch (failure) {
      flash(failure.message, true);
      return;
    }
    paintPalette();
  }
  await loadSaved();
  paint();
  await check();
}
window.openFlows = openFlows;

$("flowname").addEventListener("input", () => { FLOW.name = $("flowname").value.trim(); touch(); });

$("flowexample").onclick = async () => {
  try {
    openFlow(await api("/api/flow/example"));
    flash("The flow the lab runs: one target, peptides from the pipelines docked with ADCP, "
          + "BindCraft2's designs taken as they come, and everything simulated in HOPE-MD.");
  } catch (failure) { flash(failure.message, true); }
};

$("flowclear").onclick = () => {
  FLOW = blankFlow();
  $("flowname").value = "";
  PICKED = "";
  CHECKED = false;
  paint();
  check();
};

$("flowsave").onclick = async () => {
  FLOW.name = $("flowname").value.trim();
  if (!FLOW.name) {
    flash("Give the flow a name first: it is kept under that name.", true);
    $("flowname").focus();
    return;
  }
  try {
    SAVED = (await api("/api/flow/save", { flow: FLOW })).flows || [];
    paintSaved();
    flash("Kept as " + FLOW.name + ", beside the launcher's other settings on this computer.");
  } catch (failure) { flash(failure.message, true); }
};

$("flowforget").onclick = async () => {
  const name = FLOW.name;
  try {
    SAVED = (await api("/api/flow/delete", { name: name })).flows || [];
    paintSaved();
    flash(name + " is no longer kept. What is on the canvas is untouched.");
  } catch (failure) { flash(failure.message, true); }
};

$("flowsaved").onchange = (e) => {
  const chosen = SAVED.find((f) => f.name === e.target.value);
  if (chosen) openFlow(chosen);
  e.target.value = "";
};

$("flowlaunch").onclick = async () => {
  try {
    await api("/api/flow/launch", { flow: FLOW });
    flash("The flow is queued. Its jobs are in Results as they land.");
  } catch (failure) { flash(failure.message, true); }
};

/* a card dragged off the palette lands where it was dropped */
$("canvasgrid").addEventListener("dragover", (e) => { e.preventDefault(); });
$("canvasgrid").addEventListener("drop", (e) => {
  e.preventDefault();
  const key = e.dataTransfer.getData("text/plain");
  if (!cardOf(key)) return;
  const at = pointIn(e);
  addCard(key, [Math.max(0, Math.round(at.x - 100)), Math.max(0, Math.round(at.y - 26))]);
});
