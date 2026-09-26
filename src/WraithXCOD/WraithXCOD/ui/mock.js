// Stand-in for the C++ host when the UI is opened in a normal browser, so the
// design can be previewed and tested without a game. Inert inside WebView2.
(function () {
  "use strict";
  if (window.chrome && window.chrome.webview) return;

  const listeners = [];
  const emit = (name, data) => setTimeout(() => listeners.forEach(fn => fn({ data: { type: "event", name, data } })), 0);
  const reply = (id, result, error) => setTimeout(() => listeners.forEach(fn => fn({ data: { type: "reply", id, ok: !error, result, error } })), 8);

  let saved = {}; try { saved = JSON.parse(localStorage.getItem("greyhound-mock-settings") || "{}"); } catch (_) {}
  const settings = { exportroot: "", ...saved };
  const appDir = "C:\\SuperTerrain\\repos\\Greyhound\\src\\WraithXCOD\\x64\\Release";
  const exportRoot = () => settings.exportroot || appDir + "\\exported_files";

  // deterministic fake asset table
  const words = ["veh", "wpn", "p8", "p9", "fxanim", "ch", "mp", "zm", "t9", "c_t9", "env", "foliage", "rock", "tree", "wall", "door", "crate", "barrel", "fence", "lamp", "sign", "car", "truck", "debris", "concrete", "metal", "wood", "brick", "pipe", "cable", "roof", "window"];
  let seed = 7;
  const rnd = n => { // mulberry32
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return (((t ^ (t >>> 14)) >>> 0) % n);
  };
  const TYPES = ["model", "model", "model", "anim", "image", "image", "material", "sound", "rawfile"];
  const assets = [];
  for (let i = 0; i < 48213; i++) {
    const type = TYPES[rnd(TYPES.length)];
    const hashed = rnd(9) === 0;
    const name = hashed ? `xmodel_${(rnd(0x7fffffff) * 7919).toString(16)}` :
      [words[rnd(words.length)], words[rnd(words.length)], words[rnd(words.length)], String(rnd(40)).padStart(2, "0")].join("_");
    const status = rnd(30) === 0 ? "placeholder" : "loaded";
    let details = "";
    if (type === "model") details = `Bones: ${rnd(120)}, LODs: ${1 + rnd(5)}`;
    if (type === "anim") details = `Framerate: 30.00, Frames: ${rnd(300)}, Bones: ${rnd(90)}`;
    if (type === "image") { const s = 1 << (7 + rnd(6)); details = `Width: ${s}, Height: ${s}`; }
    if (type === "material") details = `Images: ${1 + rnd(9)}`;
    if (type === "sound") details = `${rnd(9)}s`;
    if (type === "rawfile") details = `Size: 0x${rnd(0xfffff).toString(16)}`;
    assets.push({ name, type, status, details });
  }
  let loaded = false;
  let view = [];
  let job = null;
  let generation = 1, previewToken = 0, retainedPreview = null, popup = null, transfer = 0;
  const calls = [];
  const child = new URLSearchParams(location.search).get("previewWindow") === "1";
  function emitPreview(name, data) {
    if (popup && !popup.closed && popup.GreyhoundMock) popup.GreyhoundMock.receive(name, data);
    else emit(name, data);
  }
  function replayPreview() {
    if (!retainedPreview) return;
    const { meta, buffer } = retainedPreview, transferId = ++transfer;
    emitPreview("preview.begin", { ...meta, transferId });
    const bytes = new Uint8Array(buffer);
    for (let offset = 0; offset < bytes.length; offset += 48 * 1024) {
      const part = bytes.subarray(offset, offset + 48 * 1024);
      emitPreview("preview.chunk", { requestId: meta.requestId, generation: meta.generation, transferId, offset, data: btoa(String.fromCharCode(...part)) });
    }
    emitPreview("preview.end", { requestId: meta.requestId, generation: meta.generation, transferId });
  }
  function clearPreview() { previewToken++; retainedPreview = null; emit("preview.status", { status: "cleared" }); if (popup?.GreyhoundMock) popup.GreyhoundMock.receive("preview.status", { status: "cleared" }); }
  function dockPreview() {
    if (popup && !popup.closed) popup.close(); popup = null;
    emit("preview.dockState", { poppedOut: false, retained: retainedPreview ? { requestId: retainedPreview.meta.requestId, generation: retainedPreview.meta.generation } : null }); replayPreview(); return true;
  }
  // Three independently bound pieces: duplicate material names intentionally
  // reference different color images, and the last piece has a missing image.
  function fixture(row, key) {
    const width = 64, height = 64, model = row.type === "model", meshes = [];
    const geometryBytes = model ? 3 * (4 * 36 + 6 * 4) : 0;
    const buffer = new ArrayBuffer(geometryBytes + (model ? 2 : 1) * width * height * 4), bytes = new Uint8Array(buffer), floats = new Float32Array(buffer);
    if (model) for (let piece = 0; piece < 3; piece++) {
      const vertexOffset = piece * 168, indexOffset = vertexOffset + 144, x = (piece - 1) * 1.8;
      [[x-.8,0,-.8,0,1],[x+.8,0,-.8,1,1],[x+.8,0,.8,1,0],[x-.8,0,.8,0,0]].forEach((v, i) => {
        floats.set([v[0],v[1],v[2],0,-1,0,v[3],v[4]], vertexOffset / 4 + i * 9);
        bytes.set([255,255,255,255], vertexOffset + i * 36 + 32);
      });
      new Uint32Array(buffer, indexOffset, 6).set([0,1,2,0,2,3]);
      meshes.push({ vertexOffset, vertexCount: 4, indexOffset, indexCount: 6, texture: piece < 2 ? piece : -1, materialName: "duplicate_name", sourceSubmesh: piece });
    }
    const textures = Array.from({ length: model ? 2 : 1 }, (_, t) => {
      const offset = geometryBytes + t * width * height * 4;
      for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
        const checker = ((x >> 3) + (y >> 3)) % 2 ? .6 : 1;
        bytes.set([Math.round((t ? 65 : 238) * checker), Math.round((t ? 178 : 137) * checker), Math.round((t ? 238 : 87) * checker), !model && Math.hypot(x-32,y-32)>29 ? 0 : 255], offset + (y * width + x) * 4);
      }
      return { offset, width, height, byteLength: width * height * 4, hasAlpha: !model, name: "color_" + t };
    });
    return { meta: { ...key, kind: row.type, name: row.name, byteLength: buffer.byteLength, vertexStride: 36, meshes, textures, lod: 0, missingTextures: model ? 1 : 0, vertexCount: 12, triangleCount: 6 }, buffer };
  }

  function counts() {
    const c = {};
    assets.forEach(a => c[a.type] = (c[a.type] || 0) + 1);
    return c;
  }
  function state(extra = {}) {
    return {
      loaded, generation, loading: false, busy: !!job, exportRoot: exportRoot(),
      game: loaded ? { id: "black_ops_cw", name: "Black Ops Cold War", path: "C:\\Games\\Call of Duty\\BlackOpsColdWar.exe", icon: "" } : null,
      total: loaded ? assets.length : 0, typeCounts: loaded ? counts() : {}, ...extra,
    };
  }

  function runJob(title, total, doneText) {
    let p = 0;
    job = { title };
    emit("state", state());
    const tick = setInterval(() => {
      p += 7;
      if (p >= 100 || !job) {
        clearInterval(tick);
        const cancelled = !job;
        job = null;
        emit("job", { title, state: cancelled ? "cancelled" : "done", status: cancelled ? "Stopped." : doneText, progress: 100, path: exportRoot() + "\\black_ops_cw" });
        emit("state", state());
        return;
      }
      emit("job", { title, state: "running", status: `Exporting ${Math.round(p * total / 100)} of ${total}…`, progress: p, cancellable: true });
    }, 180);
  }

  const handlers = {
    "app.init": a => { Object.keys(a.defaults).forEach(k => { if (!(k in settings)) settings[k] = a.defaults[k]; }); return { version: "v2.0 preview", settings: { ...settings }, state: state() }; },
    "app.ready": () => true,
    "app.theme": () => true,
    "app.exportRoot": () => ({ path: exportRoot() }),
    "app.about": () => ({ text: "Greyhound v2.0 (browser preview)\n\nThis is the mock host; no game is attached." }),
    "settings.set": a => { Object.assign(settings, a.values); localStorage.setItem("greyhound-mock-settings", JSON.stringify(settings)); return true; },
    "game.load": () => {
      emit("state", { ...state(), loading: true, loadingText: "Reading Black Ops Cold War asset pools…" });
      clearPreview();
      setTimeout(() => { loaded = true; generation++; view = assets.map((_, i) => i); emit("state", state({ reset: true })); }, 900);
      return true;
    },
    "game.loadFile": () => { emit("toast", { text: "File dialog opens here in the app" }); return true; },
    "game.clear": () => { clearPreview(); generation++; loaded = false; view = []; emit("state", state({ reset: true })); return true; },
    "assets.query": a => {
      clearPreview(); generation++;
      const terms = (a.text || "").toLowerCase().split(",").map(s => s.trim()).filter(s => s && !s.includes(":"));
      view = [];
      assets.forEach((x, i) => {
        if (a.type !== "all" && x.type !== a.type) return;
        if (terms.length && !terms.some(t => t.startsWith("!") ? !x.name.includes(t.slice(1)) : x.name.includes(t))) return;
        view.push(i);
      });
      if (a.sort) view.sort((p, q) => (assets[p][a.sort] || "").localeCompare(assets[q][a.sort] || "") * (a.desc ? -1 : 1));
      return { count: view.length, generation };
    },
    "assets.rows": a => view.slice(a.start, a.start + a.count).map(i => assets[i]),
    "assets.copyNames": a => a.all ? view.length : a.indices.length,
    "preview.request": a => {
      if (!loaded || a.generation !== generation) throw Error("The asset list changed. Choose Preview again.");
      const row = assets[view[a.index]]; if (!row || !["model", "image"].includes(row.type)) throw Error("Choose a model or image.");
      const token = ++previewToken, key = { requestId: a.requestId, generation };
      emitPreview("preview.status", { ...key, status: "loading", name: row.name });
      setTimeout(() => { if (token !== previewToken || !loaded) return; retainedPreview = fixture(row, key); replayPreview(); }, 220);
      return { ...key, status: "loading" };
    },
    "preview.cancel": () => { previewToken++; return true; },
    "preview.ready": () => { if (child && opener?.GreyhoundMock) opener.GreyhoundMock.connect(window); else replayPreview(); return true; },
    "preview.popout": () => {
      if (popup && !popup.closed) { popup.focus(); return true; }
      popup = window.open(location.pathname + "?previewWindow=1", "greyhound-preview", "width=920,height=720,resizable=yes");
      if (!popup) throw Error("The browser blocked the preview window.");
      emit("preview.dockState", { poppedOut: true });
      const watch = setInterval(() => { if (!popup || popup.closed) { clearInterval(watch); if (popup) dockPreview(); } }, 150);
      return true;
    },
    "preview.dock": () => child && opener?.GreyhoundMock ? opener.GreyhoundMock.dock() : dockPreview(),
    "export.selection": a => {
      const n = a.all ? view.length : a.indices.length;
      runJob(n === 1 ? "Exporting 1 asset" : `Exporting ${n.toLocaleString()} assets`, n, `Exported ${n} assets.`);
      return true;
    },
    "job.cancel": () => { job = null; return true; },
    "dialog.folder": () => "D:\\_superterrain\\greyhound_exports",
    "shell.openExportRoot": () => { emit("toast", { text: "Opens " + exportRoot() }); return true; },
    "shell.openPath": a => { emit("toast", { text: "Opens " + a.path }); return true; },
    "shell.url": () => true,
    "tools.run": a => { runJob({ placements: "Model placements", brushes: "Radiant brushes" }[a.tool] || a.tool, 40, "Saved to placements\\run_01"); return true; },
    "tools.bo4Modes": () => ({ selected: 0, overridden: false, modes: [{ label: "Off", hint: "Pick a capture mode." }, { label: "World probe", hint: "Captures world headers." }] }),
    "names.download": () => { settings.salukinamefolder = "C:\\Users\\you\\AppData\\Local\\Greyhound\\cod-name-db\\2026-09-20"; settings.salukiautoupdate = "true"; emit("settings", { ...settings }); return true; },
    "names.folder": () => true,
    "names.disable": () => { settings.salukinamefolder = ""; settings.salukiautoupdate = "false"; emit("settings", { ...settings }); return true; },
    "ask.answer": () => true,
  };

  window.GreyhoundMock = {
    calls,
    receive: emit,
    connect(win) { popup = win; popup.GreyhoundMock.receive("preview.dockState", { poppedOut: true, retained: retainedPreview ? { requestId: retainedPreview.meta.requestId, generation: retainedPreview.meta.generation } : null }); replayPreview(); },
    dock: dockPreview,
    addEventListener: (_, fn) => listeners.push(fn),
    postMessage(msg) {
      calls.push({ cmd: msg.cmd, args: msg.args });
      const h = handlers[msg.cmd];
      if (!h) return reply(msg.id, null, "Mock has no handler for " + msg.cmd);
      try { reply(msg.id, h(msg.args || {})); } catch (e) { reply(msg.id, null, e.message); }
    },
    dropFiles(files) { emit("toast", { text: "Would open " + files[0].name }); },
  };
})();
