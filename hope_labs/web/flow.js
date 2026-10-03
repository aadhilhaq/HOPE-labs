/* HOPE Labs: the flow canvas. Cards are dropped from the palette, dragged into place and linked
   socket to socket; the target is filled in on the right; what is wrong with the flow is listed
   under it, and Launch is held shut until nothing is.

   The canvas decides nothing. Which links are legal, and what is wrong with a flow, come from the
   launcher, which reads the card catalogue the runner reads on the cluster. The refusals arrive as
   a table of every pair of sockets, worked out for the target as it is filled in at that moment,
   so a drag can colour the sockets without a round trip for each one, and a refusal reads here in
   the words the catalogue gives it rather than in a second set of our own.

   The view is one of three stages at a time. The canvas is where a flow is drawn; the plan is what
   the cluster says the flow would do, read before anything is queued; the run view is the same
   cards standing where they were drawn, coloured by what has become of each. They are stages
   rather than tabs because they follow one another: a plan is read on the way to queueing a flow,
   and once the flow is queued there is nothing to go back to a plan for.

   It shares api(), flash(), el(), $(), when(), byKey() and open_tool() with app.js, which is
   loaded before it. */
"use strict";

const CANVAS_MIN = [1180, 660];     // the drawing is this big at least, and the box scrolls

/* The three states a card does not come back from without somebody asking it to. The runner's own
   words are used for all seven, here and on the page: somebody reading squeue beside this should
   find one vocabulary rather than two. */
const ENDED = ["done", "failed", "stopped"];

/* How often a flow that is still going is read again. A flow is hours to days long, so this costs
   the login node next to nothing, and it is quick enough that a card going from queued to running
   is seen rather than waited for. */
const RUN_EVERY = 20000;

let CAT = null;                     // the catalogue, read once
let FLOW = blankFlow();             // exactly the document flow.py reads and writes
let REFUSALS = {};                  // "card:port>card:port" -> why not, or ""
let PROBLEMS = [];                  // check()'s sentences, as they came
let CHECKED = false;                // whether the launcher has answered about this flow yet
let PICKED = "";                    // the node whose settings the panel shows
let WIRE = null;                    // the link being drawn, while one is
let SAVED = [];                     // the flows kept on this computer
let QUEUED = [];                    // the flows queued from this computer, newest first
let STAGE = "draw";                 // draw | plan | run
let PLAN = null;                    // what the cluster says this flow would do, while it is shown
let WATCHING = null;                // {folder, flow, status, read, why} of the flow being watched
let checkSeq = 0;
let checkTimer = 0;
let planSeq = 0;
let runTimer = 0;

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

/* Where a card sits. A flow this page drew says so; one written by hand, or queued from a file on
   the cluster, need not, and a card with nowhere to be would stop the drawing dead. Those are laid
   out as the palette lays out a card it has just been given. */
function spot(at, i) {
  if (!at || at.length < 2) return [24 + (i % 4) * 252, 24 + Math.floor(i / 4) * 176];
  return [Math.max(0, Math.round(at[0] || 0)), Math.max(0, Math.round(at[1] || 0))];
}

/* A flow document with nothing missing from it that the drawing needs. Both the canvas and the run
   view take flows out of the settings file, so both come through here rather than one of them
   trusting what it was given. */
function asDrawn(doc) {
  return {
    version: 1, name: (doc || {}).name || "", runs_root: (doc || {}).runs_root || "",
    nodes: ((doc || {}).nodes || []).map((n, i) => ({ id: n.id, card: n.card,
                                                      settings: Object.assign({}, n.settings),
                                                      at: spot(n.at, i) })),
    edges: ((doc || {}).edges || []).map((e) => ({ from: e.from, fromPort: e.fromPort,
                                                   to: e.to, toPort: e.toPort })),
  };
}

function openFlow(doc) {
  FLOW = asDrawn(doc);
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
/* Drawn twice: on the canvas, where a flow is put together, and in the run view, where the same
   cards stand where they were put and say what has become of them. One builder rather than two,
   because two would part company the first time a card grew a socket, and the whole point of the
   run view is that it is the drawing a person recognises.

   `rows` is the status answer's cards while a flow is being watched and null while one is being
   drawn, and everything that edits the drawing hangs off its being null. */
function drawFlow(box, svg, doc, rows) {
  Array.prototype.slice.call(box.querySelectorAll(".node")).forEach((n) => n.remove());
  (doc.nodes || []).forEach((node) => {
    box.appendChild(nodeBox(node, rows ? rowFor(rows, node.id) : null));
  });
  sizeBox(box, doc);
  wiresInto(svg, box, doc, rows);
}

function rowFor(rows, id) {
  return (rows || []).find((r) => r.id === id) || { id: id, state: "waiting", jobs: [] };
}

function paint() {
  drawFlow($("canvas"), $("wires"), FLOW, null);
  paintPanel();
  paintProblems();
}

function socket(node, port, side, live) {
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
  if (!live) return s;                // a watched card's sockets are read, not rewired
  if (side === "out") {
    s.addEventListener("pointerdown", (e) => startWire(e, node, port));
  } else {
    // while a link is being drawn the socket takes the pointer, so the card does not move with it
    s.addEventListener("pointerdown", (e) => { if (WIRE) e.stopPropagation(); });
  }
  return s;
}

function nodeBox(node, run) {
  const card = cardOf(node.card);
  const state = run ? (run.state || "waiting") : "";
  const box = el("div", "node" + (run ? " watched " + state : (PICKED === node.id ? " on" : "")));
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
  if (!run) {
    const off = el("button", "nx", "×");
    off.title = "Take " + (card ? card.name : node.card) + " off the canvas";
    off.onclick = (e) => { e.stopPropagation(); dropCard(node.id); };
    head.appendChild(off);
  }
  box.appendChild(head);
  if (run) {
    // On its own line rather than beside the name: every card on the canvas is the same width,
    // and a state put next to "HOPE-pipelines" leaves the name an ellipsis. The state and the job
    // ids are what is worth reading off the drawing - the ids because squeue is where a person
    // goes next - and the folder is in the list beside it, where there is room for it.
    const strip = el("div", "nrun");
    strip.appendChild(el("span", "sp " + state, state));
    if ((run.jobs || []).length) {
      strip.appendChild(el("span", "njobs", (run.jobs.length === 1 ? "job " : "jobs ")
                                            + run.jobs.join(" ")));
    }
    box.appendChild(strip);
  }
  if (card) {
    const socks = el("div", "socks");
    const left = el("div", "col in"), right = el("div", "col out");
    (card.inputs || []).forEach((p) => left.appendChild(socket(node, p, "in", !run)));
    (card.outputs || []).forEach((p) => right.appendChild(socket(node, p, "out", !run)));
    socks.appendChild(left);
    socks.appendChild(right);
    box.appendChild(socks);
  }
  if (run) {
    if (run.note) box.appendChild(el("div", "nnote", run.note));
  } else {
    box.addEventListener("pointerdown", (e) => startMove(e, node, box));
  }
  return box;
}

function sizeBox(box, doc) {
  let w = CANVAS_MIN[0], h = CANVAS_MIN[1];
  (doc.nodes || []).forEach((n) => {
    w = Math.max(w, Math.round(n.at[0] || 0) + 300);
    h = Math.max(h, Math.round(n.at[1] || 0) + 250);
  });
  box.style.width = w + "px";
  box.style.height = h + "px";
}

function pointIn(e) {
  const c = $("canvas").getBoundingClientRect();
  return { x: e.clientX - c.left, y: e.clientY - c.top };
}

function socketAt(box, id, side, port) {
  const node = box.querySelector('.node[data-node="' + id + '"]');
  return node ? node.querySelector('.sock[data-' + side + '="' + port + '"] .dot') : null;
}

/* Where a socket's dot has ended up, measured rather than worked out: a card is as tall as its own
   text made it, so the only thing that knows where its third socket is is the card. The box has to
   be on the screen for this to answer, which is why a stage is shown before it is drawn. */
function where(box, id, side, port) {
  const dot = socketAt(box, id, side, port);
  if (!dot) return null;
  const c = box.getBoundingClientRect(), r = dot.getBoundingClientRect();
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

/* The links into a given box. On the canvas each also carries a wide invisible path so it can be
   clicked off without aiming, and says why it is refused. A watched flow has neither, since there
   is nothing there to change; instead a link goes solid once the card it leaves has finished, so
   the drawing fills in as the flow runs. */
function wiresInto(svg, box, doc, rows) {
  svg.innerHTML = "";
  (doc.edges || []).forEach((edge, i) => {
    const a = where(box, edge.from, "out", edge.fromPort);
    const b = where(box, edge.to, "in", edge.toPort);
    if (!a || !b) return;
    const d = curve(a, b);
    if (rows) {
      svg.appendChild(wirePath(d, "wire"
        + (rowFor(rows, edge.from).state === "done" ? " ran" : " pending")));
      return;
    }
    const why = refusedEdge(edge);
    const hit = wirePath(d, "hit");
    hit.addEventListener("click", () => { FLOW.edges.splice(i, 1); paint(); check(); });
    const tip = document.createElementNS("http://www.w3.org/2000/svg", "title");
    tip.textContent = why ? why + " - click to take this link out" : "click to take this link out";
    hit.appendChild(tip);
    svg.appendChild(hit);
    svg.appendChild(wirePath(d, "wire" + (why ? " bad" : "")));
  });
  if (!rows && WIRE) {
    const a = where(box, WIRE.from, "out", WIRE.port);
    if (a) svg.appendChild(wirePath(curve(a, { x: WIRE.x, y: WIRE.y }), "wire live"));
  }
}

function paintWires() { wiresInto($("wires"), $("canvas"), FLOW, null); }

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
    sizeBox($("canvas"), FLOW);
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
  const a = where($("canvas"), node.id, "out", port.key) || { x: 0, y: 0 };
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

/* ------------------------------------------------------------------ the flows queued from here */
/* A queued flow runs on the cluster whether this window is open or not, so where each one landed
   is kept in the settings file with the drawing it came from. This is how somebody who signs in
   the next morning gets back to the flow they started: one choice from the list, and the run view
   reads the record the flow's own jobs have been keeping meanwhile. */
function paintQueued() {
  const pick = $("flowruns");
  pick.innerHTML = "";
  const first = el("option", null, QUEUED.length ? "Watch a queued flow…"
                                                 : "No queued flows yet");
  first.value = "";
  pick.appendChild(first);
  QUEUED.forEach((r) => {
    const o = el("option", null, (r.name || "a flow") + (r.started ? " · " + when(r.started) : ""));
    o.value = r.folder;
    o.title = r.folder;
    pick.appendChild(o);
  });
  pick.value = "";
  pick.disabled = !QUEUED.length;
}

async function loadQueued() {
  try { QUEUED = (await api("/api/flow/queued")).runs || []; } catch (failure) { QUEUED = []; }
  paintQueued();
}

/* ------------------------------------------------------------------ the stages */
/* Which of the three the view is showing. The editing controls go with the canvas: on the other
   two stages they would act on a drawing nobody is looking at, and Clear on top of a plan a person
   is about to queue would be a trap. The two lists stay, because picking another flow or another
   run is a way out of both sheets. */
function stage(which) {
  STAGE = which;
  $("flowwrap").hidden = which !== "draw";
  $("flowplan").hidden = which !== "plan";
  $("flowrun").hidden = which !== "run";
  ["namebox", "flowsave", "flowforget", "flowexample", "flowclear"].forEach((id) => {
    $(id).hidden = which !== "draw";
  });
  if (which !== "run") {
    clearTimeout(runTimer);
    runTimer = 0;
  }
}

/* The path with a button that puts it on the clipboard, as a handed-over run has in a tool's tab.
   A page may write to the clipboard only inside a click, and on some machines Chrome refuses it
   outright, so the fallback selects the text for Ctrl+C rather than leaving nothing to copy. */
function pathLine(path) {
  const row = el("div", "pathrow");
  const code = el("code", null, path);
  row.appendChild(code);
  const copy = el("button", "btn sm", "Copy");
  copy.title = "Put this folder on the clipboard";
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(path);
      flash("Copied. Paste it wherever the folder is wanted.");
    } catch (refused) {
      const range = document.createRange();
      range.selectNodeContents(code);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      flash("Selected. Press Ctrl+C to copy it.", true);
    }
  };
  row.appendChild(copy);
  return row;
}

/* ------------------------------------------------------------------ the plan */
/* Launch queues nothing. It asks the cluster what the flow would do and shows that, because the
   press commits an allocation that can run for days and until it has been read there is nothing
   to decide on. Queue it, in the bar underneath, is the only thing on this page that queues. */
async function showPlan() {
  FLOW.name = $("flowname").value.trim();
  const mine = ++planSeq;
  PLAN = null;
  stage("plan");
  paintPlan();
  let got;
  try {
    got = await api("/api/flow/plan", { flow: FLOW });
  } catch (failure) {
    if (mine !== planSeq || STAGE !== "plan") return;
    PLAN = { failed: failure.message };
    paintPlan();
    return;
  }
  // A later plan has already been asked for, or Back was pressed while the cluster worked this one
  // out: this answer is about a flow nobody is looking at, and a plan that is about the wrong flow
  // is worse than no plan, because it is the thing Queue it is pressed on the strength of.
  if (mine !== planSeq || STAGE !== "plan") return;
  PLAN = got;
  paintPlan();
}

function planStep(row, n) {
  const li = el("li", "planstep");
  const card = cardOf(row.card);
  const head = el("div", "psthead");
  head.appendChild(el("span", "pstn", String(n)));
  const badge = el("span", "pbadge");
  if (card) badge.appendChild(cardGlyph(card));
  head.appendChild(badge);
  head.appendChild(el("span", "pstname", row.name || row.card));
  head.appendChild(el("span", "pstafter", (row.waits_for || []).length
    ? "after " + row.waits_for.join(" and ")
    : "starts at once: nothing arrives at it"));
  li.appendChild(head);
  const facts = el("dl", "pstfacts");
  // The numbers behind the cost are the whole reason for reading this, so they are a row of their
  // own rather than a parenthesis after what the card queues.
  [["queues", row.queues], ["the numbers", row.scale]].forEach((pair) => {
    if (!pair[1]) return;
    facts.appendChild(el("dt", null, pair[0]));
    facts.appendChild(el("dd", null, pair[1]));
  });
  if (row.lands_in) {
    facts.appendChild(el("dt", null, "lands in"));
    const dd = el("dd");
    dd.appendChild(pathLine(row.lands_in));
    facts.appendChild(dd);
  }
  li.appendChild(facts);
  return li;
}

function planBlock(cls, title, lines) {
  const box = el("div", cls);
  box.appendChild(el("div", "plab", title));
  const list = el("ul", "notelist");
  lines.forEach((line) => list.appendChild(el("li", null, line)));
  box.appendChild(list);
  return box;
}

function paintPlan() {
  const body = $("planbody");
  const why = $("planwhy");
  body.innerHTML = "";
  why.innerHTML = "";
  const wide = el("div", "sheetwide");
  body.appendChild(wide);
  $("planqueue").hidden = true;
  $("planqueue").disabled = false;
  $("planqueue").textContent = "Queue it";

  if (!PLAN) {
    wide.appendChild(el("p", "empty", "Working out what this flow would do, on the cluster…"));
    why.appendChild(el("p", "pgood", "Nothing has been queued."));
    return;
  }
  if (PLAN.failed) {
    wide.appendChild(planBlock("planbad", "The plan could not be worked out", [PLAN.failed]));
    why.appendChild(el("p", "runbad", "Nothing has been queued."));
    return;
  }

  const head = el("div", "sheethead");
  head.appendChild(el("h2", null, PLAN.name || "this flow"));
  head.appendChild(el("p", "sheetwhy", "Nothing is queued yet. This is what Queue it would commit, "
    + "worked out on the cluster where the tools actually are."));
  wide.appendChild(head);

  const where = el("div", "planwhere");
  where.appendChild(el("span", "plab", "the flow's own folder"));
  where.appendChild(pathLine(PLAN.folder || ""));
  wide.appendChild(where);

  // The notes come before the cards. They are the warnings a person most needs - that two tracks
  // arriving at the simulation double the number of runs, that a length is a long commitment - and
  // under a list of five cards they would be read after the decision rather than before it.
  if ((PLAN.notes || []).length) {
    wide.appendChild(planBlock("planotes", "Before you queue this", PLAN.notes));
  }
  if ((PLAN.problems || []).length) {
    wide.appendChild(planBlock("planbad", "This flow cannot be queued yet", PLAN.problems));
  }

  const steps = el("ol", "plansteps");
  (PLAN.cards || []).forEach((row, i) => steps.appendChild(planStep(row, i + 1)));
  wide.appendChild(steps);

  if ((PLAN.problems || []).length) {
    why.appendChild(el("p", "runbad", "Go back and put that right first. There is nothing to "
      + "queue while a flow is refused."));
    return;
  }
  $("planqueue").hidden = false;
  why.appendChild(el("p", "pgood", (PLAN.cards || []).length + " cards, in that order. Nothing is "
    + "queued until Queue it is pressed, and once it is, the flow carries on whether this window "
    + "is open or not."));
}

/* ------------------------------------------------------------------ a flow that is running */
/* Whether anything is still to happen, which is what the refreshing and the two buttons turn on. */
function busy(got) {
  return !!got && (got.cards || []).some((c) => ENDED.indexOf(c.state) < 0);
}

/* The one word for the whole flow. The record's own `state` is not used for it: that calls a flow
   failed as soon as anything in it did not finish, which is every card of a flow somebody stopped
   on purpose, and a person who pressed Stop should not be told their flow failed. */
function overall(got) {
  const rows = (got && got.cards) || [];
  if (!rows.length) return "waiting";
  if (rows.some((r) => r.state === "failed")) return "failed";
  if (busy(got)) return "running";
  if (rows.every((r) => r.state === "done")) return "done";
  return "stopped";
}

/* How long ago the record was read. app.js's when() is for run folders, where a minute's
   resolution is plenty; here somebody is watching, and "1 min ago" the instant after pressing
   Refresh reads as though nothing had happened. */
function ago(ms) {
  const gap = Math.round((Date.now() - ms) / 1000);
  if (gap < 10) return "just now";
  if (gap < 90) return gap + " seconds ago";
  return when(Math.round(ms / 1000));
}

function watch(folder) {
  const kept = QUEUED.find((r) => r.folder === folder);
  WATCHING = { folder: folder, flow: kept && kept.flow ? asDrawn(kept.flow) : null,
               status: null, read: 0, why: "" };
  stage("run");
  paintRun();
  return readRun();
}

async function readRun() {
  if (!WATCHING) return;
  const folder = WATCHING.folder;
  let got = null, failed = "";
  try {
    got = await api("/api/flow/status", { folder: folder });
  } catch (failure) {
    failed = failure.message;
  }
  // Another flow may have been picked while the cluster was answering about this one; that answer
  // belongs to a folder nobody is looking at any more.
  if (!WATCHING || WATCHING.folder !== folder) return;
  // A read that failed says so in the bar but leaves the last answer on the screen. A connection
  // that drops for a minute is the ordinary case, and blanking a flow a person is watching over
  // one missed read would look like the flow had gone.
  if (got) WATCHING.status = got;
  WATCHING.why = failed;
  WATCHING.read = Date.now();
  paintRun();
  later();
}

/* Read it again while anything is still to happen, and not once everything has ended: a finished
   flow does not change again, and a timer left running on one would wake the login node for an
   answer nobody is waiting for. */
function later() {
  clearTimeout(runTimer);
  runTimer = 0;
  if (STAGE !== "run" || !WATCHING || !busy(WATCHING.status)) return;
  runTimer = setTimeout(() => { readRun(); }, RUN_EVERY);
}

/* A card as the list beside the drawing has it: what became of it, why, whose jobs were its own,
   and where its work is. A finished card's folder is the thing a person actually came for, so it
   is offered the way Results hands a run on - the path on the clipboard, and the tool that reads
   it opened on a tab of its own, because the tools cannot yet be opened on a folder. */
function runCard(row) {
  const card = cardOf(row.card);
  const box = el("div", "rcard " + row.state);
  const head = el("div", "rchead");
  const badge = el("span", "pbadge");
  if (card) badge.appendChild(cardGlyph(card));
  head.appendChild(badge);
  head.appendChild(el("span", "pstname", row.name || row.card));
  head.appendChild(el("span", "sp " + row.state, row.state));
  box.appendChild(head);
  if (row.note) box.appendChild(el("p", "rcnote", row.note));
  if ((row.jobs || []).length) {
    const jobs = el("div", "rcjobs");
    jobs.appendChild(el("span", "plab", row.jobs.length === 1 ? "its job" : "its jobs"));
    jobs.appendChild(el("code", null, row.jobs.join(" ")));
    box.appendChild(jobs);
  }
  if (row.rundir) {
    const where = el("div", "rcwhere");
    where.appendChild(el("span", "plab", row.state === "done" ? "what it left" : "its run folder"));
    where.appendChild(pathLine(row.rundir));
    box.appendChild(where);
    const to = row.state === "done" && card && card.tool ? byKey(card.tool) : null;
    if (to) {
      const acts = el("div", "acts");
      const open = el("button", "btn sm next", "Open in " + to.name);
      open.title = "Copy this folder and open " + to.name + " on it";
      open.onclick = () => open_tool(card.tool, open, row.rundir);
      acts.appendChild(open);
      box.appendChild(acts);
    }
  }
  if (row.changed) box.appendChild(el("div", "rcwhen", "last changed " + when(row.changed)));
  return box;
}

function paintRun() {
  const head = $("runhead"), list = $("runcards"), why = $("runwhy");
  head.innerHTML = "";
  list.innerHTML = "";
  why.innerHTML = "";
  if (!WATCHING) return;
  const got = WATCHING.status;
  const rows = (got && got.cards) || [];
  const drawing = WATCHING.flow;

  const name = (got && got.name) || (drawing && drawing.name) || "this flow";
  const title = el("h2", null, name);
  if (got) title.appendChild(el("span", "sp " + overall(got), overall(got)));
  head.appendChild(title);
  // How far it has got and where it is, on one line: this bar sits over the drawing, and every
  // row it takes is a row of the flow a person cannot see.
  const line = el("div", "runline");
  line.appendChild(el("span", "runhow", got
    ? got.done + " of " + got.of + " cards done. Read " + ago(WATCHING.read) + "."
    : "Reading the record this flow's own jobs keep…"));
  line.appendChild(el("span", "plab", "the flow's own folder"));
  line.appendChild(pathLine(WATCHING.folder));
  head.appendChild(line);

  // The drawing is the one kept with the folder when the flow was queued. A flow queued from a
  // file on the cluster, or from a settings file since replaced, has none, and the list beside it
  // is then the whole view rather than half of it.
  $("runcanvasgrid").hidden = !drawing;
  if (drawing) drawFlow($("runcanvas"), $("runwires"), drawing, rows);

  if (!rows.length) {
    list.appendChild(el("p", "empty", WATCHING.why
      ? "The flow's record could not be read."
      : "Reading the flow's record…"));
  }
  rows.forEach((row) => list.appendChild(runCard(row)));
  if (!drawing && rows.length) {
    list.appendChild(el("p", "phint", "The drawing this flow was queued from is not kept on this "
      + "computer, so only the cards are shown."));
  }

  if (WATCHING.why) {
    why.appendChild(el("p", "runbad", WATCHING.why));
  } else if (got && got.note) {
    why.appendChild(el("p", "runbad", got.note));
  } else if (got) {
    why.appendChild(el("p", "pgood", busy(got)
      ? "Read again every " + Math.round(RUN_EVERY / 1000) + " seconds while anything is left to "
        + "happen. It runs whether this window is open or not."
      : "Nothing more will happen on its own."));
  }

  // Carry on queues the cards that have not finished, so it is offered only once nothing of the
  // flow is left in the queue: pressed while a card is still running it would say so and do
  // nothing, which is a worse answer than not offering it.
  const running = busy(got);
  const finished = rows.length && rows.every((r) => r.state === "done");
  $("runcarry").hidden = !got || running || finished;
  $("runcarry").disabled = false;
  $("runstop").hidden = !running;
  $("runstop").disabled = false;
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
  await loadQueued();
  // Coming back to the view leaves it on the stage it was left on: somebody who went to Results to
  // look something up has not stopped watching their flow.
  if (STAGE === "plan") return paintPlan();
  if (STAGE === "run") {
    paintRun();
    return readRun();
  }
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

$("flowruns").onchange = (e) => {
  const folder = e.target.value;
  e.target.value = "";
  if (folder) watch(folder);
};

/* Launch reads the plan out of the cluster and shows it. Queue it is the press that commits. */
$("flowlaunch").onclick = () => { showPlan(); };

$("planback").onclick = () => {
  PLAN = null;
  stage("draw");
  paint();
  check();
};

$("planqueue").onclick = async () => {
  const button = $("planqueue");
  button.disabled = true;
  button.textContent = "queueing…";
  try {
    const got = await api("/api/flow/launch", { flow: FLOW });
    await loadQueued();
    flash((PLAN && PLAN.name ? PLAN.name : "The flow") + " is queued, in " + got.folder
          + ". It carries on whether this window is open or not.");
    PLAN = null;
    await watch(got.folder);
    return;
  } catch (failure) { flash(failure.message, true); }
  button.disabled = false;
  button.textContent = "Queue it";
};

$("runback").onclick = () => {
  WATCHING = null;
  stage("draw");
  paint();
  check();
};

$("runreload").onclick = () => { readRun(); };

$("runcarry").onclick = async () => {
  if (!WATCHING) return;
  const button = $("runcarry");
  button.disabled = true;
  button.textContent = "queueing…";
  try {
    await api("/api/flow/resume", { folder: WATCHING.folder });
    flash("Carrying on from the first card that has not finished. What has already run is left "
          + "where it is and is not run again.");
  } catch (failure) { flash(failure.message, true); }
  button.textContent = "Carry on";
  await readRun();
};

$("runstop").onclick = async () => {
  if (!WATCHING) return;
  const button = $("runstop");
  button.disabled = true;
  try {
    await api("/api/flow/stop", { folder: WATCHING.folder });
    flash("Cancelled what this flow still had in the queue. What has finished is on disk and "
          + "stays there; Carry on picks it up from the first card that did not.");
  } catch (failure) { flash(failure.message, true); }
  await readRun();
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
