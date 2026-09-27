// Greyhound v2 front end. Talks to the C++ core through a small JSON bridge:
//   page -> host:  {id, cmd, args}            host -> page: {type:"reply", id, ok, result|error}
//   host -> page:  {type:"event", name, data} (state, row, job, ask, notice, toast)
// Outside WebView2 (plain browser preview) mock.js stands in for the host.
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = n => Number(n || 0).toLocaleString("en-US");
const PREVIEW_WINDOW = new URLSearchParams(location.search).get("previewWindow") === "1";
document.body.classList.toggle("preview-window", PREVIEW_WINDOW);

// ---------------------------------------------------------------- bridge

const Bridge = (() => {
  const wv = window.chrome && window.chrome.webview;
  const host = wv || window.GreyhoundMock;
  const pending = new Map();
  const handlers = {};
  let seq = 0;

  host.addEventListener("message", e => {
    const m = e.data;
    if (!m) return;
    if (m.type === "reply") {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      m.ok ? p.resolve(m.result) : p.reject(new Error(m.error || "Failed"));
    } else if (m.type === "event") {
      (handlers[m.name] || []).forEach(fn => fn(m.data || {}));
    }
  });

  return {
    native: !!wv,
    webview: wv,
    call(cmd, args = {}) {
      const id = ++seq;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        host.postMessage({ id, cmd, args });
      });
    },
    // Only WebView2 can hand the host real file paths for dropped files.
    dropFiles(files) {
      if (wv && wv.postMessageWithAdditionalObjects) wv.postMessageWithAdditionalObjects({ id: ++seq, cmd: "game.dropFile", args: {} }, files);
      else if (host.dropFiles) host.dropFiles(files);
    },
    on(name, fn) { (handlers[name] ||= []).push(fn); },
  };
})();

async function run(cmd, args) {
  try { return await Bridge.call(cmd, args); }
  catch (e) { toast(e.message, "err"); throw e; }
}

// ---------------------------------------------------------------- constants

const TYPES = {
  model: { label: "Models", one: "Model", c: "var(--t-model)" },
  anim: { label: "Anims", one: "Anim", c: "var(--t-anim)" },
  image: { label: "Images", one: "Image", c: "var(--t-image)" },
  sound: { label: "Sounds", one: "Sound", c: "var(--t-sound)" },
  material: { label: "Materials", one: "Material", c: "var(--t-material)" },
  decal: { label: "Decals", one: "Decal", c: "var(--t-material)" },
  rawfile: { label: "Raw files", one: "Raw file", c: "var(--t-raw)" },
  effect: { label: "Effects", one: "Effect", c: "var(--t-effect)" },
  terrain: { label: "Terrain", one: "TerrainGfx", c: "var(--t-terrain)" },
};
const STATUS = {
  loaded: "Loaded", exported: "Exported", processing: "Exporting", placeholder: "Placeholder",
  error: "Error", notloaded: "Not loaded", unknown: "Unknown",
};
const GAMES_CW = ["black_ops_cw"], GAMES_BO4 = ["black_ops_4"];

// ---------------------------------------------------------------- app state

const S = {
  loaded: false, loading: false, game: null, total: 0, typeCounts: {},
  exportRoot: "", busy: false,
  type: "all", text: "", sort: { key: null, dir: 1 },
  view: 0, gen: 0, hostGeneration: 0, cache: new Map(), inflight: new Set(),
  sel: new Set(), selAll: false, anchor: -1, cursor: -1,
  settings: {},
};
const PAGE = 200;
const ROW_H = 34;

// ---------------------------------------------------------------- navigation

function showPage(name) {
  $$(".nav button").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  $$(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + name));
  if (name === "library") requestAnimationFrame(renderRows);
}
$$(".nav button").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page)));
$$("[data-click]").forEach(b => b.addEventListener("click", () => $("#" + b.dataset.click).click()));

// ---------------------------------------------------------------- state from host

Bridge.on("state", applyState);

function applyState(st) {
  if (st.generation !== undefined) S.hostGeneration = st.generation;
  Object.assign(S, {
    loaded: !!st.loaded, loading: !!st.loading, game: st.game || null,
    total: st.total || 0, typeCounts: st.typeCounts || {}, busy: !!st.busy,
  });
  if (st.exportRoot !== undefined) setExportRoot(st.exportRoot);

  const chip = $("#gameChip");
  chip.classList.toggle("live", S.loaded);
  $("#gameName").textContent = S.game ? S.game.name : (S.loading ? "Loading…" : "No game loaded");
  $("#gameMeta").innerHTML = S.loaded
    ? `<span class="dot"></span>${fmt(S.total)} assets${S.game && S.game.file ? " · file" : ""}`
    : `<span class="dot"></span>${S.loading ? "Reading asset pools" : "Idle"}`;
  chip.title = S.game && S.game.path ? S.game.path : "";
  $("#gameIcon").innerHTML = S.game && S.game.icon
    ? `<img alt="" src="${S.game.icon}">`
    : `<svg width="18" height="18"><use href="#i-cube"/></svg>`;

  $("#libEmpty").classList.toggle("hidden", S.loaded || S.loading);
  $("#libLoading").classList.toggle("hidden", !S.loading);
  $("#libTable").classList.toggle("hidden", !S.loaded || S.loading);
  $("#libBar").classList.toggle("hidden", !S.loaded || S.loading);
  $("#filters").classList.toggle("hidden", !S.loaded || S.loading);
  $("#libraryWorkspace").classList.toggle("hidden", !S.loaded || S.loading);
  $("#layoutBar").classList.toggle("hidden", !S.loaded || S.loading);
  if (st.loadingText) $("#loadingText").textContent = st.loadingText;

  // The empty state carries its own Load / Open buttons; don't show them twice.
  $(".toolbar").classList.toggle("hidden", !S.loaded && !S.loading);
  $("#search").disabled = !S.loaded;
  $("#btnLoad").disabled = S.loading || S.busy;
  $("#btnOpenFile").disabled = S.loading || S.busy;
  $("#btnClear").disabled = !S.loaded || S.busy;
  $("#btnLoad").classList.toggle("primary", !S.loaded);
  $("#btnLoad").innerHTML = S.loaded
    ? `<svg><use href="#i-refresh"/></svg>Reload`
    : `<svg><use href="#i-play"/></svg>Load game`;

  if (st.reset) {
    // A fresh load or unload: the host's view is the whole list again.
    S.text = ""; $("#search").value = "";
    S.type = "all"; S.sort = { key: null, dir: 1 };
    $$(".thead .th .arrow").forEach(a => a.textContent = "");
    S.view = S.total;
    resetView();
  }
  renderFilters();
  updateGates();
  refreshSettingsUI();
  updateBar();
}

// ---------------------------------------------------------------- library: filters, query

function renderFilters() {
  const f = $("#filters");
  const present = Object.keys(TYPES).filter(t => S.typeCounts[t]);
  if (!present.includes(S.type) && S.type !== "all") S.type = "all";
  f.innerHTML = [`<button class="filter ${S.type === "all" ? "on" : ""}" data-type="all">All <span class="n">${fmt(S.total)}</span></button>`]
    .concat(present.map(t => `<button class="filter ${S.type === t ? "on" : ""}" data-type="${t}" style="--c:${TYPES[t].c}"><span class="sw"></span>${TYPES[t].label} <span class="n">${fmt(S.typeCounts[t])}</span></button>`))
    .join("");
  $$(".filter", f).forEach(b => b.addEventListener("click", () => {
    S.type = b.dataset.type; renderFilters(); query();
  }));
}

let searchTimer = 0;
$("#search").addEventListener("input", e => {
  S.text = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(query, 160);
});
$("#search").addEventListener("keydown", e => {
  if (e.key === "Enter") { clearTimeout(searchTimer); query(); }
  if (e.key === "Escape") { e.target.value = ""; S.text = ""; query(); }
  if (e.key === "ArrowDown") { e.preventDefault(); $("#tbody").focus(); moveCursor(1, false); }
});
$("#searchHelp").addEventListener("click", e => { e.stopPropagation(); $("#searchPop").classList.toggle("show"); });
document.addEventListener("click", e => { if (!e.target.closest(".popover")) $("#searchPop").classList.remove("show"); });

$$(".thead .th").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.sort;
  if (S.sort.key !== k) S.sort = { key: k, dir: 1 };
  else if (S.sort.dir === 1) S.sort.dir = -1;
  else S.sort = { key: null, dir: 1 };
  $$(".thead .th .arrow").forEach(a => a.textContent = "");
  if (S.sort.key) th.querySelector(".arrow").textContent = S.sort.dir === 1 ? "↑" : "↓";
  query();
}));

async function query() {
  if (!S.loaded || PREVIEW_WINDOW) return;
  Preview.cancelPending();
  const res = await run("assets.query", { text: S.text, type: S.type, sort: S.sort.key || "", desc: S.sort.dir < 0 });
  S.view = res.count;
  if (res.generation !== undefined) S.hostGeneration = res.generation;
  resetView();
}

function resetView() {
  S.gen++;
  Preview.cancelPending();
  S.cache.clear(); S.inflight.clear();
  S.sel.clear(); S.selAll = false; S.anchor = -1; S.cursor = -1;
  if (!S.loaded) S.view = 0;
  $("#spacer").style.height = (S.view * ROW_H) + "px";
  $("#tbody").scrollTop = 0;
  renderRows();
  updateBar();
}

// ---------------------------------------------------------------- library: virtual table

const tbody = $("#tbody");
let rowPool = [];
let rafQueued = false;
function scheduleRender() { if (!rafQueued) { rafQueued = true; requestAnimationFrame(() => { rafQueued = false; renderRows(); }); } }
tbody.addEventListener("scroll", scheduleRender);
new ResizeObserver(scheduleRender).observe(tbody);

function rowAt(i) {
  const page = S.cache.get(Math.floor(i / PAGE));
  return page ? page[i % PAGE] : null;
}

function fetchPage(p) {
  if (PREVIEW_WINDOW) return;
  if (S.cache.has(p) || S.inflight.has(p)) return;
  const gen = S.gen;
  S.inflight.add(p);
  Bridge.call("assets.rows", { start: p * PAGE, count: PAGE }).then(rows => {
    if (gen !== S.gen) return;
    S.inflight.delete(p);
    S.cache.set(p, rows);
    scheduleRender();
    if (Math.floor(S.cursor / PAGE) === p) Preview.request();
  }).catch(() => S.inflight.delete(p));
}

function isSel(i) { return S.selAll || S.sel.has(i); }

function renderRows() {
  if (!S.loaded || !tbody.clientHeight) return;
  const top = tbody.scrollTop, h = tbody.clientHeight;
  const first = Math.max(0, Math.floor(top / ROW_H) - 6);
  const last = Math.min(S.view - 1, Math.ceil((top + h) / ROW_H) + 6);
  for (let p = Math.floor(first / PAGE); p <= Math.floor(Math.max(first, last) / PAGE); p++) fetchPage(p);

  const need = Math.max(0, last - first + 1);
  while (rowPool.length < need) {
    const el = document.createElement("div");
    el.className = "trow";
    el.innerHTML = `<div class="name"></div><div><span class="tpill"><span class="sw"></span><span></span></span></div><div><span class="status"><span class="d"></span><span></span></span></div><div class="det"></div>`;
    tbody.appendChild(el);
    rowPool.push(el);
  }
  rowPool.forEach((el, k) => {
    const i = first + k;
    if (k >= need) { el.style.display = "none"; return; }
    el.style.display = "";
    el.style.top = (i * ROW_H) + "px";
    el.dataset.i = i;
    el.classList.toggle("sel", isSel(i));
    el.classList.toggle("focused", S.cursor === i);
    const r = rowAt(i);
    const [nameEl, typeEl, statusEl, detEl] = el.children;
    if (!r) {
      nameEl.textContent = "…"; nameEl.className = "name pending";
      typeEl.firstChild.style.visibility = "hidden";
      statusEl.firstChild.style.visibility = "hidden";
      detEl.textContent = "";
      return;
    }
    nameEl.className = "name"; nameEl.textContent = r.name; nameEl.title = r.name;
    const t = TYPES[r.type] || { one: r.type, c: "var(--text-faint)" };
    typeEl.firstChild.style.visibility = "";
    typeEl.firstChild.style.setProperty("--c", t.c);
    typeEl.firstChild.lastChild.textContent = t.one;
    statusEl.firstChild.style.visibility = "";
    statusEl.firstChild.className = "status " + r.status;
    statusEl.firstChild.lastChild.textContent = STATUS[r.status] || r.status;
    detEl.textContent = r.details || "";
  });
  updatePreviewButton();
}

Bridge.on("row", d => {
  const r = rowAt(d.i);
  if (r && d.status) { r.status = d.status; scheduleRender(); }
});
Bridge.on("rows-dirty", () => { S.cache.clear(); scheduleRender(); });

// selection
tbody.addEventListener("mousedown", e => {
  const el = e.target.closest(".trow");
  if (!el) return;
  tbody.focus();
  select(+el.dataset.i, e.ctrlKey || e.metaKey, e.shiftKey, e.button === 2);
});
tbody.addEventListener("dblclick", e => {
  const el = e.target.closest(".trow");
  if (el) exportIndices([+el.dataset.i]);
});
tbody.addEventListener("contextmenu", e => {
  e.preventDefault();
  if (!e.target.closest(".trow")) return;
  const m = $("#rowMenu");
  m.classList.add("show");
  m.style.left = Math.min(e.clientX, innerWidth - m.offsetWidth - 8) + "px";
  m.style.top = Math.min(e.clientY, innerHeight - m.offsetHeight - 8) + "px";
});
document.addEventListener("mousedown", e => { if (!e.target.closest("#rowMenu")) $("#rowMenu").classList.remove("show"); });
$$("#rowMenu button").forEach(b => b.addEventListener("click", () => {
  $("#rowMenu").classList.remove("show");
  ({ preview: () => Preview.request(), export: exportSelected, copy: () => copyNames("\n"), copycsv: () => copyNames(","), selectall: selectAll })[b.dataset.m]();
}));

function select(i, ctrl, shift, keepIfSelected) {
  if (S.cursor !== i) Preview.cancelPending();
  if (keepIfSelected && isSel(i)) { S.cursor = i; renderRows(); updateBar(); Preview.request(); return; }
  if (S.selAll) { S.selAll = false; if (ctrl) for (let k = 0; k < S.view; k++) S.sel.add(k); }
  if (shift && S.anchor >= 0) {
    if (!ctrl) S.sel.clear();
    const [a, b] = S.anchor < i ? [S.anchor, i] : [i, S.anchor];
    for (let k = a; k <= b; k++) S.sel.add(k);
  } else if (ctrl) {
    S.sel.has(i) ? S.sel.delete(i) : S.sel.add(i);
    S.anchor = i;
  } else {
    S.sel.clear(); S.sel.add(i); S.anchor = i;
  }
  S.cursor = i;
  renderRows(); updateBar();
  Preview.request();
}
function selectAll() { if (!S.view) return; S.selAll = true; S.sel.clear(); if (S.cursor < 0) S.cursor = 0; renderRows(); updateBar(); }
function selectedCount() { return S.selAll ? S.view : S.sel.size; }

function moveCursor(d, shift) {
  if (!S.view) return;
  const i = Math.max(0, Math.min(S.view - 1, (S.cursor < 0 ? -1 : S.cursor) + d));
  select(i, false, shift, false);
  const top = i * ROW_H;
  if (top < tbody.scrollTop) tbody.scrollTop = top;
  else if (top + ROW_H > tbody.scrollTop + tbody.clientHeight) tbody.scrollTop = top + ROW_H - tbody.clientHeight;
}

tbody.addEventListener("keydown", e => {
  const page = Math.max(1, Math.floor(tbody.clientHeight / ROW_H) - 1);
  if (e.key === "ArrowDown") { e.preventDefault(); moveCursor(1, e.shiftKey); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveCursor(-1, e.shiftKey); }
  else if (e.key === "PageDown") { e.preventDefault(); moveCursor(page, e.shiftKey); }
  else if (e.key === "PageUp") { e.preventDefault(); moveCursor(-page, e.shiftKey); }
  else if (e.key === "Home") { e.preventDefault(); moveCursor(-S.view, e.shiftKey); }
  else if (e.key === "End") { e.preventDefault(); moveCursor(S.view, e.shiftKey); }
  else if (e.key === "Enter") { e.preventDefault(); exportSelected(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "a") { e.preventDefault(); selectAll(); }
  else if (e.ctrlKey && e.key.toLowerCase() === "c") { e.preventDefault(); copyNames("\n"); }
  else if (e.ctrlKey && e.key.toLowerCase() === "x") { e.preventDefault(); copyNames(","); }
});

document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.key.toLowerCase() === "f") { e.preventDefault(); showPage("library"); $("#search").focus(); $("#search").select(); }
  if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r")) e.preventDefault();
  if (e.key === "Escape") { $("#searchPop").classList.remove("show"); $("#rowMenu").classList.remove("show"); }
});

function selectionArgs() { return S.selAll ? { all: true } : { indices: [...S.sel].sort((a, b) => a - b) }; }

async function copyNames(sep) {
  if (!selectedCount()) return;
  const n = await run("assets.copyNames", { ...selectionArgs(), sep });
  toast(`Copied ${fmt(n)} name${n === 1 ? "" : "s"}`);
}

function updateBar() {
  updatePreviewButton();
  const n = selectedCount();
  const shown = S.view;
  const filtered = S.text || S.type !== "all";
  $("#countText").innerHTML = n
    ? `<b>${fmt(n)}</b> selected of <b>${fmt(shown)}</b>`
    : filtered ? `<b>${fmt(shown)}</b> of ${fmt(S.total)} shown` : `<b>${fmt(shown)}</b> assets`;
  $("#btnExportSel").disabled = !n || S.busy;
  $("#btnExportAll").disabled = !shown || S.busy;
  $("#btnExportAll").textContent = filtered ? `Export all ${fmt(shown)} shown` : "Export all";
  $("#btnExportSel").innerHTML = `<svg><use href="#i-export"/></svg>` + (n > 1 ? `Export ${fmt(n)}` : "Export selected");
}

// ---------------------------------------------------------------- actions

$("#btnLoad").addEventListener("click", () => run("game.load"));
$("#btnOpenFile").addEventListener("click", () => run("game.loadFile"));
$("#btnClear").addEventListener("click", () => run("game.clear"));
$("#btnExportSel").addEventListener("click", exportSelected);
$("#btnExportAll").addEventListener("click", () => run("export.selection", { all: true }));
$("#btnPreview").addEventListener("click", () => Preview.request());

function exportSelected() { if (selectedCount()) run("export.selection", selectionArgs()); }
function exportIndices(indices) { run("export.selection", { indices }); }

$("#outChip").addEventListener("click", () => run("shell.openExportRoot"));
$$("[data-url]").forEach(a => a.addEventListener("click", () => run("shell.url", { which: a.dataset.url })));
$('[data-action="about"]').addEventListener("click", async () => {
  const info = await run("app.about");
  notice("About Greyhound", info.text);
});

function setExportRoot(p) {
  S.exportRoot = p;
  $("#outPath").textContent = p;
  $("#outChip").title = "Open " + p;
  const el = $("#exportRootPath");
  if (el) el.textContent = p;
}

// drag & drop package files
let dragDepth = 0;
document.addEventListener("dragenter", e => { if (hasFiles(e)) { dragDepth++; document.body.classList.add("dragging"); } });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
document.addEventListener("dragover", e => { e.preventDefault(); });
document.addEventListener("drop", e => {
  e.preventDefault();
  dragDepth = 0; document.body.classList.remove("dragging");
  if (e.dataTransfer.files.length) Bridge.dropFiles(e.dataTransfer.files);
});
function hasFiles(e) { return [...(e.dataTransfer?.types || [])].includes("Files"); }

// ---------------------------------------------------------------- jobs, dialogs, toasts

let jobShown = false;
Bridge.on("job", j => {
  const box = $("#job");
  jobShown = true;
  box.classList.add("show");
  box.classList.toggle("done", j.state === "done");
  box.classList.toggle("failed", j.state === "failed");
  $("#jobTitle").textContent = j.title || "Working";
  $("#jobStatus").textContent = j.status || "";
  const st = $("#jobState");
  st.className = "state tag " + ({ done: "ok", failed: "warn", cancelled: "muted" }[j.state] || "");
  st.textContent = { running: "Running", done: "Finished", failed: "Needs a look", cancelled: "Cancelled" }[j.state] || "Running";
  const bar = $("#jobBar");
  const indet = j.state === "running" && (j.progress == null || j.progress < 0);
  bar.classList.toggle("indet", indet);
  bar.firstElementChild.style.width = indet ? "" : Math.max(0, Math.min(100, j.state === "running" ? j.progress : 100)) + "%";
  const running = j.state === "running";
  $("#jobCancel").hidden = !running || !j.cancellable;
  $("#jobDone").hidden = running;
  $("#jobOpen").hidden = running || !j.path;
  $("#jobOpen").dataset.path = j.path || "";
});
$("#jobCancel").addEventListener("click", () => { run("job.cancel"); $("#jobStatus").textContent = "Cancelling after the current asset…"; });
$("#jobDone").addEventListener("click", () => { $("#job").classList.remove("show"); jobShown = false; });
$("#jobOpen").addEventListener("click", e => run("shell.openPath", { path: e.currentTarget.dataset.path }));

function dialog(title, text, buttons) {
  return new Promise(resolve => {
    $("#modalTitle").textContent = title;
    $("#modalText").textContent = text;
    const mb = $("#modalButtons");
    mb.innerHTML = "";
    buttons.forEach(b => {
      const el = document.createElement("button");
      el.className = "btn" + (b.primary ? " primary" : "");
      el.textContent = b.label;
      el.addEventListener("click", () => { $("#modalBg").classList.remove("show"); resolve(b.id); });
      mb.appendChild(el);
    });
    $("#modalBg").classList.add("show");
    (mb.querySelector(".primary") || mb.lastChild).focus();
  });
}
function notice(title, text) { return dialog(title, text, [{ id: "ok", label: "OK", primary: true }]); }

Bridge.on("ask", async a => {
  const answer = await dialog(a.title, a.text, a.buttons);
  Bridge.call("ask.answer", { id: a.id, answer });
});
Bridge.on("notice", n => notice(n.title, n.text));
Bridge.on("toast", t => toast(t.text, t.kind));

function toast(text, kind) {
  const el = document.createElement("div");
  el.className = "toast" + (kind === "err" ? " err" : "");
  el.textContent = text;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 5200 : 2600);
}

// ---------------------------------------------------------------- map tools + diagnostics gating

$$("[data-tool]").forEach(b => b.addEventListener("click", () => run("tools.run", { tool: b.dataset.tool })));

function gateText(need) {
  const id = S.game && S.game.id;
  const ok = {
    bo4cw: GAMES_CW.includes(id) || GAMES_BO4.includes(id),
    cw: GAMES_CW.includes(id),
    bo4: GAMES_BO4.includes(id),
  }[need];
  if (ok && S.loaded && !S.game.file) return "";
  return { bo4cw: "Load a Black Ops 4 or Cold War map first", cw: "Load a Cold War map first", bo4: "Load a Black Ops 4 map first" }[need];
}
function updateGates() {
  $$("[data-need]").forEach(n => {
    const text = gateText(n.dataset.need);
    n.textContent = text;
    const btn = n.parentElement.querySelector("[data-tool]");
    if (btn) btn.disabled = !!text || S.busy;
  });
  const tag = $("#toolsGameTag");
  tag.textContent = S.loaded && S.game ? S.game.name : "No map";
  tag.className = "tag" + (S.loaded ? "" : " muted");
  $$('[data-tool="verifyRuntime"],[data-tool="verifyExport"]').forEach(b => b.disabled = S.busy);
}

// ---------------------------------------------------------------- settings

const CHECK = `<svg><use href="#i-check"/></svg>`;
const MODEL_FORMATS = [
  ["export_castmdl", "CAST", "Blender · Maya"], ["export_semodel", "SEModel", "Maya plugin"],
  ["export_gltf", "glTF", "text + bin"], ["export_glb", "GLB", "single file"],
  ["export_obj", "OBJ", "static mesh"], ["export_ma", "Maya", ".ma scene"],
  ["export_smd", "SMD", "Valve"], ["export_xna", "XNALara", ".mesh.ascii"],
  ["export_xmexport", "XMODEL_EXPORT", "CoD modtools"], ["export_xmbin", "XMODEL_BIN", "CoD modtools"],
];

// Mirrors GeneralSettings' combo: map data wins, then probe depth.
function cwMode(s) {
  if (s.cwmapdata === "true") return "mapdata";
  if (s.cwprobepayloads === "true") return s.cwdeepProbe === "true" ? "deep" : "probe";
  return "headers";
}

// Every row maps to settings keys. get/set allow one control to drive several keys.
const SCHEMA = [
  {
    id: "output", title: "Output", sub: "Where exports are written.",
    rows: [
      { type: "exportRoot", label: "Export folder", hint: "Each game gets its own folder inside, e.g. black_ops_cw\\xmodels." },
    ],
  },
  {
    id: "library", title: "Library", sub: "What Load game reads. Fewer types load faster.",
    rows: [
      {
        type: "chips", label: "Asset types to load", items: [
          ["showxmodel", "Models", "", true], ["showxanim", "Anims", "", true], ["showximage", "Images", "", false],
          ["showxsounds", "Sounds", "", false], ["showxmtl", "Materials", "", false], ["showxrawfiles", "Raw files", "", false],
          ["showxterrain", "TerrainGfx", "BO4 · CW", true],
          ["showxdecals", "Decals", "BO4", false],
        ]
      },
      { type: "seg", key: "assetsortmethod", def: "Name", label: "Initial sort", hint: "Order after loading. Click a column header to re-sort any time.", options: [["Name", "Name"], ["Details", "Details"], ["None", "Game order"]] },
    ],
  },
  {
    id: "models", title: "Models",
    rows: [
      { type: "chips", label: "Formats", hint: "Every selected format is written for each model.", items: MODEL_FORMATS.map(([k, l, s]) => [k, l, s, k === "export_semodel"]) },
      { type: "seg", key: "exportalllods", def: "false", label: "Level of detail", options: [["false", "Highest detail only"], ["true", "All LODs"]] },
      {
        type: "seg", label: "Textures", hint: "A shared folder avoids exporting the same image many times.",
        options: [["off", "Don't export"], ["model", "Beside each model"], ["global", "Shared folder"]],
        get: s => s.exportmodelimg !== "true" ? "off" : s.global_images === "true" ? "global" : "model",
        set: v => ({ exportmodelimg: v === "off" ? "false" : "true", global_images: v === "global" ? "true" : "false" }),
        keys: { exportmodelimg: "true", global_images: "false" },
      },
      {
        type: "more", label: "More model options", rows: [
          { type: "toggle", key: "exportimgnames", def: "false", label: "Material image list", hint: "Writes each material's images and settings as a text file." },
          { type: "toggle", key: "mdlmtlfolders", def: "true", label: "Group textures by material", hint: "One folder per material instead of one flat folder." },
          { type: "toggle", key: "skipprevmodel", def: "true", label: "Skip models already exported", hint: "Checks the export folder and skips existing files." },
          { type: "toggle", key: "exportvtxcolor", def: "false", label: "Vertex colours" },
          { type: "toggle", key: "reverse_lod_numbering", def: "false", label: "Number LODs from the highest detail", hint: "BO4 / Cold War: LOD0 is the most detailed." },
          { type: "toggle", key: "exporthitbox", def: "false", label: "Hitbox", hint: "Black Ops 1 and 3 only." },
        ]
      },
    ],
  },
  {
    id: "anims", title: "Animations",
    rows: [
      { type: "chips", label: "Formats", items: [["export_seanim", "SEAnim", "Maya plugin", true], ["export_castanim", "CAST", "Blender · Maya", false], ["export_directxanim", "Direct XAnim", "WaW / BO1 modtools", false]] },
      { type: "seg", key: "directxanim_ver", def: "17", label: "Direct XAnim target", hint: "Only used when Direct XAnim is selected.", options: [["17", "World at War"], ["19", "Black Ops 1"]], when: s => s.export_directxanim === "true" },
      { type: "toggle", key: "skipprevanim", def: "true", label: "Skip animations already exported" },
    ],
  },
  {
    id: "images", title: "Images",
    rows: [
      { type: "seg", key: "exportimg", def: "PNG", label: "Format", hint: "PNG for Black Ops 3 modtools, TGA for older modtools. Some DDS formats need editor plugins.", options: [["PNG", "PNG"], ["TGA", "TGA"], ["TIFF", "TIFF"], ["DDS", "DDS"]] },
      { type: "toggle", key: "patchnormals", def: "true", label: "Rebuild normal maps", hint: "Restores the blue channel the game strips from packed normals." },
      { type: "toggle", key: "patchcolor", def: "true", label: "Clean colour maps", hint: "Removes specular data packed into the alpha channel." },
      { type: "toggle", key: "skipprevimg", def: "true", label: "Skip images already exported" },
    ],
  },
  {
    id: "sounds", title: "Sounds",
    rows: [
      { type: "seg", key: "exportsnd", def: "WAV", label: "Format", hint: "FLAC is lossless and smaller, but modtools can't read it.", options: [["WAV", "WAV"], ["FLAC", "FLAC"]] },
      { type: "toggle", key: "keepsndpath", def: "true", label: "Keep the game's folder structure", hint: "Recommended: many sounds share a file name." },
      { type: "toggle", key: "skipprevsound", def: "true", label: "Skip sounds already exported" },
      { type: "toggle", key: "skipblankaudio", def: "false", label: "Skip silent audio in SAB files" },
      { type: "toggle", key: "usesabindexbo4", def: "false", label: "Name BO4 sounds by SAB name + index" },
    ],
  },
  {
    id: "terrain", title: "Terrain",
    sub: "Cold War exports terrain model packages. Black Ops 4 uses its separate raw source capture in Diagnostics.",
    rows: [
      { type: "note", label: "Terrain and decals", hintFn: () => GAMES_BO4.includes(S.game?.id)
        ? "BO4: use Diagnostics → Terrain source capture. The terrain probe keeps decal data separate. Load Decals in the Library to export supported BO3 assets independently."
        : "Cold War: terrain material layers are included; separate decals are omitted. Raw source capture remains available in Diagnostics. Native BO3 conversion of Cold War decals is not supported yet." },
      { type: "seg", key: "terrainarea", def: "whole", label: "Cold War area", when: () => !S.loaded || GAMES_CW.includes(S.game?.id), options: [["whole", "Whole map"], ["nearby", "5 × 5 tiles near the camera"]] },
      { type: "seg", key: "terrainmodelformats", def: "cast", label: "Cold War format", when: () => !S.loaded || GAMES_CW.includes(S.game?.id), options: [["cast", "CAST"], ["selected", "My model formats"]] },
      { type: "folder", key: "terrainoutputroot", label: "Terrain output folder", hint: "Used by terrain model exports and raw source captures for both games. Empty uses the export folder above.", empty: "Same as export folder" },
    ],
  },
  {
    id: "decals", title: "Decals",
    sub: "Select a decal in the Library and export a folder to copy into Black Ops 3 Mod Tools. Enable Decals under Library, then reload the game.",
    rows: [
      { type: "note", label: "Supported decals", hint: "BO4 color/reveal grunge materials are supported. Other shader families are listed with their support status. Cold War decals use a different format and are not converted yet." },
      { type: "seg", key: "decalplacements", def: "false", label: "Decal output", options: [["false", "Reusable asset"], ["true", "Asset + original placements"]], hint: "Placements add a Radiant prefab at the source map coordinates. Unsupported placements are reported; terrain export stays independent." },
    ],
  },
  {
    id: "names", title: "Asset names",
    sub: "Black Ops 4, Cold War and newer games store many names as hashes. A name database turns them back into readable names.",
    rows: [{ type: "saluki" }],
  },
  {
    id: "appearance", title: "Appearance",
    rows: [{ type: "seg", key: "uitheme", def: "system", label: "Theme", options: [["system", "Match Windows"], ["dark", "Dark"], ["light", "Light"]] }],
  },
  {
    id: "research", title: "Cold War research", badge: "Advanced",
    sub: "Adds raw Cold War pools to the Library as cw_pool rows. Export them like any other asset. None of these are needed for normal exports.",
    rows: [
      {
        type: "chips", label: "Pool groups to load", items: [
          ["showcwworld", "Map worlds"], ["showcwnav", "Navigation"], ["showcwcollision", "Collision"], ["showcwentities", "Entities / dynamic models"],
          ["showcwtriggers", "Triggers"], ["showcwfx", "Effects"], ["showcwai", "AI / animation tables"],
        ].map(([k, l]) => [k, l, "", false])
      },
      {
        type: "select", label: "Pool export mode",
        options: [["headers", "Headers only"], ["mapdata", "Map data + readback verification"], ["probe", "Probe referenced bytes"], ["deep", "Deep probe (experimental)"]],
        get: cwMode,
        set: v => ({ cwmapdata: v === "mapdata" ? "true" : "false", cwprobepayloads: v === "probe" || v === "deep" ? "true" : "false", cwdeepProbe: v === "deep" ? "true" : "false" }),
        keys: { cwmapdata: "false", cwprobepayloads: "false", cwdeepProbe: "false" },
        hintFn: s => ({
          headers: "Pool headers only. Referenced geometry and entity properties are not collected.",
          mapdata: "Captures the sections chosen below and verifies them by reading them back.",
          probe: "Headers plus small samples of referenced memory. Samples may be incomplete.",
          deep: "Bounded reference probes plus the sections below. Collision topology is experimental.",
        })[cwMode(s)],
      },
      {
        type: "chips", label: "Map data sections", hint: "Used by the Map data and Deep probe modes.",
        when: s => s.cwmapdata === "true" || s.cwdeepProbe === "true",
        items: [["cwcaptureplacements", "Placements", "", true], ["cwcaptureentities", "Entities / triggers", "", true], ["cwcapturecollision", "Collision payloads", "", true], ["cwcapturesplines", "Splined model inputs", "", false]],
      },
      { type: "toggle", key: "cwcollisioncodeprobe", def: "false", label: "Capture collision reader code instead of pool data", hint: "Research only. Needs the researched CW build." },
    ],
  },
];

// Map-tool option groups rendered into the tool cards.
const GROUPS = {
  placements: [
    { type: "toggle", key: "cwnonstaticplacements", def: "false", label: "Include non-static placements and entity classes", hint: "Cold War." },
    { type: "toggle", key: "cwproxyfilter", def: "false", label: "Drop combined building proxies", hint: "Removes proxies that duplicate captured detail models. Removals are recorded." },
    { type: "toggle", key: "cworganizeplacements", def: "false", label: "Sort into per-category folders", hint: "Makes a sorted copy of the export.", requires: "cwnonstaticplacements" },
    { type: "toggle", key: "cwverifyplacements", def: "false", label: "Verify against the captured bytes", requires: "cwnonstaticplacements" },
  ],
  brushes: [
    { type: "toggle", key: "cwradiantbrushes", def: "false", label: "Also build brushes during Cold War pool exports", hint: "Optional Cold War shortcut. The Export brushes button supports both BO4 and Cold War.", also: v => v === "true" ? { showcwcollision: "true" } : {} },
    { type: "toggle", key: "cwradianttypes", def: "true", label: "Assign stock tool materials for Cold War", hint: "BO4 always uses verified stock tool assignments. Substitutions and differences are listed in the export report." },
    { type: "toggle", key: "cwradiantvolumes", def: "true", label: "Include triggers, volumes and entity JSON" },
    { type: "toggle", key: "cwfloattriangles", def: "false", label: "Also write collision triangles as OBJ", hint: "Cold War reference geometry; does not create triangle brushes." },
    { type: "toggle", key: "cwmodeltriangles", def: "false", label: "Include BO4 triangle collision surfaces", hint: "Decoded JSON." },
  ],
};

function allRows(rows, out = []) {
  rows.forEach(r => { out.push(r); if (r.rows) allRows(r.rows, out); });
  return out;
}
function settingDefaults() {
  const d = { exportroot: "", salukinamefolder: "", salukiautoupdate: "false", salukirevision: "", bo4capturemode: "0", previewlayout: "list", previewdivider: "0.5" };
  const rows = allRows(SCHEMA.flatMap(s => s.rows).concat(GROUPS.placements, GROUPS.brushes));
  rows.forEach(r => {
    if (r.key) d[r.key] = r.def ?? "";
    if (r.keys) Object.assign(d, r.keys);
    if (r.items) r.items.forEach(([k, , , def]) => d[k] = def ? "true" : "false");
  });
  return d;
}

async function setSettings(changes) {
  Object.assign(S.settings, changes);
  await run("settings.set", { values: changes });
  refreshSettingsUI();
}

function rowHTML(r, i) {
  const id = `r${i}`;
  const lbl = `<div class="lbl"><div class="t">${esc(r.label)}${r.badge ? ` <span class="tag muted">${esc(r.badge)}</span>` : ""}</div>${r.hint || r.hintFn ? `<div class="h" data-hint="${id}">${esc(r.hint || "")}</div>` : ""}</div>`;
  switch (r.type) {
    case "note":
      return `<div class="row" data-row="${id}">${lbl}</div>`;
    case "toggle":
      return `<div class="row" data-row="${id}">${lbl}<label class="switch"><input type="checkbox" data-id="${id}"><span class="track"></span></label></div>`;
    case "seg":
      return `<div class="row" data-row="${id}">${lbl}<div class="seg" data-id="${id}">${r.options.map(([v, l]) => `<button data-v="${esc(v)}">${esc(l)}</button>`).join("")}</div></div>`;
    case "select":
      return `<div class="row" data-row="${id}">${lbl}<select data-id="${id}">${r.options.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></div>`;
    case "chips":
      return `<div class="row stack" data-row="${id}">${lbl}<div class="chips" data-id="${id}">${r.items.map(([k, l, sub]) => `<button class="chip" data-k="${k}"><span class="box">${CHECK}</span>${esc(l)}${sub ? ` <span class="sub">${esc(sub)}</span>` : ""}</button>`).join("")}</div></div>`;
    case "folder":
      return `<div class="row stack" data-row="${id}">${lbl}<div style="display:flex;gap:8px;align-items:center"><div class="path" style="flex:1" data-path="${id}"></div><button class="btn sm" data-pick="${id}">Choose…</button><button class="btn sm ghost" data-clear="${id}">Reset</button></div></div>`;
    case "exportRoot":
      return `<div class="row stack">${lbl}<div style="display:flex;gap:8px;align-items:center"><div class="path" style="flex:1" id="exportRootPath"></div><button class="btn sm" id="exportRootPick">Choose…</button><button class="btn sm ghost" id="exportRootOpen" title="Open in Explorer"><svg><use href="#i-folder"/></svg></button><button class="btn sm ghost" id="exportRootReset">Default</button></div></div>`;
    case "saluki":
      return `<div class="row stack"><div class="lbl"><div class="t">Name database <span class="tag muted" id="salukiState"></span></div><div class="h" id="salukiHint"></div></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn sm primary" id="salukiDownload">Download / update</button><button class="btn sm" id="salukiFolder">Use a local folder…</button><button class="btn sm ghost" id="salukiLink">cod-name-db on GitHub</button><button class="btn sm ghost danger" id="salukiDisable">Turn off</button></div></div>
        <div class="row"><div class="lbl"><div class="t">Update automatically</div><div class="h">Checks once a day when loading assets.</div></div><label class="switch"><input type="checkbox" id="salukiAuto"><span class="track"></span></label></div>`;
    case "more":
      return `<details class="more"><summary>${esc(r.label)}</summary><div class="rows">${r.rows.map((x, k) => rowHTML(x, `${i}_${k}`)).join("")}</div></details>`;
  }
  return "";
}

const ROWS = new Map();
function indexRows(rows, prefix) {
  rows.forEach((r, k) => {
    const id = `${prefix}${k}`;
    ROWS.set(`r${id}`, r);
    if (r.rows) indexRows(r.rows, `${id}_`);
  });
}

function renderSettings() {
  const body = $("#settingsBody");
  SCHEMA.forEach((sec, si) => {
    const el = document.createElement("div");
    el.className = "section";
    el.id = "set-" + sec.id;
    const normal = sec.rows.filter(r => r.type !== "more");
    const more = sec.rows.filter(r => r.type === "more");
    el.innerHTML = `<h3>${esc(sec.title)}${sec.badge ? ` <span class="tag muted">${esc(sec.badge)}</span>` : ""}</h3>${sec.sub ? `<p class="sub">${esc(sec.sub)}</p>` : ""}
      <div class="card"><div class="rows">${normal.map(r => rowHTML(r, `${si}_${sec.rows.indexOf(r)}`)).join("")}</div>${more.map(r => rowHTML(r, `${si}_${sec.rows.indexOf(r)}`)).join("")}</div>`;
    body.appendChild(el);
    indexRows(sec.rows, `${si}_`);
  });
  Object.entries(GROUPS).forEach(([g, rows]) => {
    $(`[data-group="${g}"]`).innerHTML = rows.map((r, k) => rowHTML(r, `${g}_${k}`)).join("");
    indexRows(rows, `${g}_`);
  });
  $("#toc").innerHTML = SCHEMA.map(s => `<a data-to="set-${s.id}">${esc(s.title)}</a>`).join("");
  $$("#toc a").forEach(a => a.addEventListener("click", () => $("#" + a.dataset.to).scrollIntoView({ behavior: "smooth", block: "start" })));
  const sc = $("#settingsScroll");
  sc.addEventListener("scroll", () => {
    let cur = SCHEMA[0].id;
    const top = sc.getBoundingClientRect().top;
    SCHEMA.forEach(s => { if ($("#set-" + s.id).getBoundingClientRect().top - top <= 120) cur = s.id; });
    if (sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 4) cur = SCHEMA[SCHEMA.length - 1].id;
    $$("#toc a").forEach(a => a.classList.toggle("on", a.dataset.to === "set-" + cur));
  });
  wireSettings();
}

function wireSettings() {
  document.addEventListener("change", e => {
    const id = e.target.dataset && e.target.dataset.id;
    const r = id && ROWS.get(id);
    if (!r) return;
    if (r.type === "toggle") {
      const v = e.target.checked ? "true" : "false";
      setSettings({ [r.key]: v, ...(r.also ? r.also(v) : {}) });
    } else if (r.type === "select") {
      setSettings(r.set ? r.set(e.target.value) : { [r.key]: e.target.value });
    }
  });
  document.addEventListener("click", e => {
    const segBtn = e.target.closest(".seg button");
    if (segBtn) {
      const r = ROWS.get(segBtn.parentElement.dataset.id);
      if (r) setSettings(r.set ? r.set(segBtn.dataset.v) : { [r.key]: segBtn.dataset.v });
      return;
    }
    const chip = e.target.closest(".chip");
    if (chip && chip.parentElement.dataset.id) {
      const k = chip.dataset.k;
      setSettings({ [k]: S.settings[k] === "true" ? "false" : "true" });
      return;
    }
    const pick = e.target.closest("[data-pick]");
    if (pick) {
      const r = ROWS.get(pick.dataset.pick);
      run("dialog.folder", { title: r.label, initial: S.settings[r.key] || S.exportRoot }).then(p => p && setSettings({ [r.key]: p }));
      return;
    }
    const clr = e.target.closest("[data-clear]");
    if (clr) { setSettings({ [ROWS.get(clr.dataset.clear).key]: "" }); return; }
  });

  $("#exportRootPick").addEventListener("click", async () => {
    const p = await run("dialog.folder", { title: "Choose where Greyhound writes exports", initial: S.exportRoot });
    if (p) { await setSettings({ exportroot: p }); setExportRoot((await run("app.exportRoot")).path); }
  });
  $("#exportRootReset").addEventListener("click", async () => { await setSettings({ exportroot: "" }); setExportRoot((await run("app.exportRoot")).path); });
  $("#exportRootOpen").addEventListener("click", () => run("shell.openExportRoot"));

  $("#salukiDownload").addEventListener("click", () => run("names.download"));
  $("#salukiFolder").addEventListener("click", () => run("names.folder"));
  $("#salukiDisable").addEventListener("click", () => run("names.disable"));
  $("#salukiLink").addEventListener("click", () => run("shell.url", { which: "saluki" }));
  $("#salukiAuto").addEventListener("change", e => e.target.checked ? run("names.download") : setSettings({ salukiautoupdate: "false" }));
}

function refreshSettingsUI() {
  const s = S.settings;
  ROWS.forEach((r, id) => {
    const rowEl = $(`[data-row="${id}"]`);
    if (rowEl && r.when) rowEl.classList.toggle("hidden", !r.when(s));
    if (rowEl && r.requires) {
      const on = s[r.requires] === "true";
      rowEl.classList.toggle("disabled", !on);
      const inp = rowEl.querySelector("input");
      if (inp) inp.disabled = !on;
    }
    const hint = $(`[data-hint="${id}"]`);
    if (hint && r.hintFn) hint.textContent = r.hintFn(s);
    if (r.type === "toggle") { const el = $(`input[data-id="${id}"]`); if (el) el.checked = s[r.key] === "true"; }
    if (r.type === "seg") {
      const v = r.get ? r.get(s) : s[r.key];
      $$(`.seg[data-id="${id}"] button`).forEach(b => b.classList.toggle("on", b.dataset.v === v));
    }
    if (r.type === "select") { const el = $(`select[data-id="${id}"]`); if (el) el.value = r.get ? r.get(s) : s[r.key]; }
    if (r.type === "chips") $$(`.chips[data-id="${id}"] .chip`).forEach(c => c.classList.toggle("on", s[c.dataset.k] === "true"));
    if (r.type === "folder") { const el = $(`[data-path="${id}"]`); if (el) { el.textContent = s[r.key] || r.empty; el.style.color = s[r.key] ? "" : "var(--text-faint)"; } }
  });
  const folder = s.salukinamefolder, auto = s.salukiautoupdate === "true";
  $("#salukiState").textContent = folder ? (auto ? "Downloaded" : "Local folder") : "Off";
  $("#salukiState").className = "tag " + (folder ? "ok" : "muted");
  $("#salukiHint").textContent = folder ? folder : "Optional. Only fills in names Greyhound couldn't resolve; existing names are kept.";
  $("#salukiAuto").checked = auto;
  $("#salukiDisable").disabled = !folder;
  applyTheme();
}

Bridge.on("settings", vals => { Object.assign(S.settings, vals); refreshSettingsUI(); });

// ---------------------------------------------------------------- theme

const media = matchMedia("(prefers-color-scheme: dark)");
media.addEventListener("change", applyTheme);
let lastDark = null;
function applyTheme() {
  const pref = S.settings.uitheme || "system";
  const dark = pref === "dark" || (pref === "system" && media.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  if (dark !== lastDark) { lastDark = dark; Bridge.call("app.theme", { dark }).catch(() => { }); }
}

// ---------------------------------------------------------------- BO4 diagnostic modes

async function loadBo4Modes() {
  const modes = await run("tools.bo4Modes");
  const sel = $("#bo4Mode");
  sel.innerHTML = modes.modes.map((m, i) => `<option value="${i}">${esc(m.label)}</option>`).join("");
  sel.value = String(modes.selected);
  const hint = () => { $("#bo4Hint").textContent = modes.modes[+sel.value]?.hint || ""; };
  hint();
  sel.disabled = modes.overridden;
  if (modes.overridden) $("#bo4Hint").textContent = "Set by the GREYHOUND_BO4_WORLD_PROBE environment variable.";
  sel.addEventListener("change", () => { hint(); setSettings({ bo4capturemode: sel.value }); });
}

// ---------------------------------------------------------------- boot

function updatePreviewButton() {
  const row = rowAt(S.cursor), available = S.loaded && !S.loading && row && ["model", "image", "terrain"].includes(row.type);
  $("#btnPreview").disabled = !available;
  $("#menuPreview").disabled = !available;
  $("#btnPreview").title = available ? `Preview ${row.name}` : "Focus a model, image, or terrain to preview it";
}

const Preview = (() => {
  let renderer = null, serial = 0, pending = null, retained = null, layout = "list", share = .5, poppedOut = false;
  const workspace = $("#libraryWorkspace"), search = $("#search").closest(".search"), toolbar = $("#page-library>.toolbar");
  const message = (text, error = false) => {
    const el = $("#previewMessage"); el.classList.toggle("hidden", !text); el.classList.toggle("error", error);
    el.querySelector("span").textContent = text;
  };
  const error = e => { pending = null; message(e.message, true); $("#previewInfo").textContent = "Preview unavailable"; };
  const ensureRenderer = () => renderer || (renderer = new GreyhoundPreview.Renderer($("#previewCanvas"), error));
  const assembler = new GreyhoundPreview.Assembler(value => {
    try {
      ensureRenderer().load(value);
      const m = value.meta; retained = { requestId: m.requestId, generation: m.generation }; pending = null;
      $("#previewName").textContent = m.name || "Asset preview"; $("#previewName").title = m.name || "";
      $("#previewStage").classList.toggle("image", m.kind === "image");
      $("#previewInfo").textContent = m.kind === "image" ? `${fmt(m.textures[0].width)} × ${fmt(m.textures[0].height)}${m.textures[0].firstSlice ? " · first slice" : ""}` :
        m.kind === "terrain" ? `${fmt(m.triangleCount)} triangles · coarse preview · ${m.sectorCount ? "BO4 layer colors" : "source color"}` :
        `${fmt(m.triangleCount ?? m.meshes.reduce((n, p) => n + p.indexCount / 3, 0))} triangles · LOD ${m.lod ?? 0} · ${fmt(m.missingTextures || 0)} missing textures`;
      $("#previewHint").textContent = m.kind === "image" ? "Drag to pan · Scroll to zoom · Checkerboard shows transparency" : "Drag to orbit · Shift-drag or right-drag to pan · Scroll to zoom";
      message("");
    } catch (e) { error(e); }
  }, error);
  const same = (a, b) => a && a.requestId === b.requestId && a.generation === b.generation;
  function clear() {
    pending = null; retained = null; assembler.cancel(); renderer?.clear();
    $("#previewName").textContent = "Asset preview"; $("#previewInfo").textContent = "Preview loads automatically on selection.";
    $("#previewStage").classList.remove("image"); message("Select a model, image, or terrain to preview it.");
  }
  function cancelPending() {
    if (!pending) return;
    pending = null; assembler.cancel(); Bridge.call("preview.cancel").catch(() => {});
    if (retained) message(""); else message("Select a model, image, or terrain to preview it.");
  }
  function setLayout(value, persist = true) {
    layout = ["list", "split", "viewer"].includes(value) ? value : "list";
    workspace.dataset.layout = layout;
    $$("[data-layout]", $("#layoutBar")).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.layout === layout)));
    if (layout === "viewer") $("#viewerSearchSlot").append(search); else toolbar.prepend(search);
    $("#previewDivider").tabIndex = layout === "split" ? 0 : -1;
    if (persist && !PREVIEW_WINDOW) setSettings({ previewlayout: layout }).catch(() => {});
    scheduleRender(); renderer?.schedule();
  }
  function setShare(value, persist = false) {
    share = GreyhoundPreview.clamp(Number.isFinite(value) ? value : .5, .2, .75);
    workspace.style.setProperty("--list-share", `${share * 100}%`);
    $("#previewDivider").setAttribute("aria-valuenow", String(Math.round(share * 100)));
    if (persist && !PREVIEW_WINDOW) setSettings({ previewdivider: String(share) }).catch(() => {});
    scheduleRender(); renderer?.schedule();
  }
  async function request() {
    if (!S.loaded || S.loading || PREVIEW_WINDOW || S.cursor < 0) return;
    const row = rowAt(S.cursor);
    // Keyboard navigation or a click can focus a row before its page arrives.
    if (!row) { fetchPage(Math.floor(S.cursor / PAGE)); return; }
    if (!["model", "image", "terrain"].includes(row.type)) return;
    cancelPending(); if (layout === "list") setLayout("split");
    const key = { requestId: ++serial, generation: S.hostGeneration }; pending = key; assembler.expect(key.requestId, key.generation);
    message(`Loading ${row.name}…`); $("#previewInfo").textContent = "Reading preview…";
    try { const result = await Bridge.call("preview.request", { ...key, index: S.cursor }); if (same(pending, key) && result?.status !== "loading") error(Error(result.message || (result?.status === "stale" ? "The asset list changed. Choose Preview again." : "This asset is not available for preview."))); }
    catch (e) { if (same(pending, key)) error(e); }
  }
  function begin(meta) {
    if (!same(pending, meta) && !same(retained, meta)) return false;
    assembler.expect(meta.requestId, meta.generation); assembler.accept("begin", meta); return true;
  }
  Bridge.on("preview.status", data => {
    if (data.status === "cleared") { clear(); return; }
    if (PREVIEW_WINDOW && data.status === "loading" && data.generation >= S.hostGeneration) { pending = data; assembler.expect(data.requestId, data.generation); }
    if (!same(pending, data)) return;
    if (data.status === "loading") message(data.message || `Loading ${data.name || "preview"}…`);
    if (data.status === "error") error(Error(data.message || data.error || "Preview unavailable"));
    if (data.status === "cancelled") { pending = null; assembler.cancel(); message(retained ? "" : "Select a model, image, or terrain to preview it."); }
  });
  Bridge.on("preview.begin", begin);
  Bridge.on("preview.chunk", d => assembler.accept("chunk", d));
  Bridge.on("preview.end", d => assembler.accept("end", d));
  Bridge.on("preview.dockState", d => {
    poppedOut = !!d.poppedOut;
    // A newer asset may have completed entirely in the separate window.
    if (d.retained) retained = d.retained;
    if (poppedOut && !PREVIEW_WINDOW) renderer?.clear();
    $("#previewDetached").classList.toggle("hidden", PREVIEW_WINDOW || !poppedOut);
    $("#previewPopout").textContent = PREVIEW_WINDOW || poppedOut ? "Dock" : "Pop out";
    renderer?.schedule();
  });
  if (Bridge.webview) Bridge.webview.addEventListener("sharedbufferreceived", e => {
    let buffer;
    try {
      const extra = typeof e.additionalData === "string" ? JSON.parse(e.additionalData) : e.additionalData;
      if (extra?.type !== "preview") return;
      const m = extra.manifest; buffer = e.getBuffer();
      if (same(pending, m) || same(retained, m)) { assembler.expect(m.requestId, m.generation); assembler.shared(m, buffer); }
    } catch (e) { error(e); }
    finally { if (buffer) Bridge.webview.releaseBuffer(buffer); }
  });
  $$("#layoutBar [data-layout]").forEach(b => b.addEventListener("click", () => setLayout(b.dataset.layout)));
  const divider = $("#previewDivider"); let dragging = false;
  divider.addEventListener("pointerdown", e => { if (layout !== "split") return; dragging = true; divider.setPointerCapture(e.pointerId); e.preventDefault(); });
  divider.addEventListener("pointermove", e => { if (!dragging) return; const r = workspace.getBoundingClientRect(); setShare((e.clientX - r.left) / Math.max(1, r.width - 12)); });
  divider.addEventListener("pointerup", () => { if (dragging) { dragging = false; setShare(share, true); } });
  divider.addEventListener("pointercancel", () => { dragging = false; });
  divider.addEventListener("keydown", e => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return; e.preventDefault(); setShare(e.key === "Home" ? .2 : e.key === "End" ? .75 : share + (e.key === "ArrowRight" ? .025 : -.025), true); });
  $("#previewFit").addEventListener("click", () => renderer?.fit());
  $("#previewCanvas").addEventListener("previewrestore", () => Bridge.call("preview.ready").catch(error));
  $("#previewZoomIn").addEventListener("click", () => renderer?.zoom(1.25));
  $("#previewZoomOut").addEventListener("click", () => renderer?.zoom(.8));
  $("#previewPopout").addEventListener("click", () => Bridge.call(PREVIEW_WINDOW || poppedOut ? "preview.dock" : "preview.popout").catch(error));
  $("#previewDock").addEventListener("click", () => Bridge.call("preview.dock").catch(error));
  return { request, cancelPending, clear, setLayout, setShare, restore() { setLayout(S.settings.previewlayout || "list", false); setShare(Number(S.settings.previewdivider ?? .5)); } };
})();

(async function boot() {
  renderSettings();
  const init = await run("app.init", { defaults: settingDefaults() });
  $("#ver").textContent = init.version;
  S.settings = init.settings;
  refreshSettingsUI();
  Preview.restore();
  applyState(init.state);
  if (!PREVIEW_WINDOW) loadBo4Modes().catch(() => { });
  Bridge.call("app.ready").catch(() => { });
  Bridge.call("preview.ready").catch(() => { });
})();
