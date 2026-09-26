// Opt-in integration smoke against an already launched Greyhound WebView.
// The caller owns launching/stopping Greyhound and restoring its settings.
"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), { execFileSync } = require("node:child_process");
const { chromium } = require("playwright");
const endpoint = process.argv[2], nativePid = Number(process.argv[3]), output = process.argv[4];
if (!endpoint || !Number.isInteger(nativePid) || !output) throw Error("Usage: node preview_native_smoke.cjs <CDP endpoint> <Greyhound PID> <output directory>");
fs.mkdirSync(output, { recursive: true });
const report = { endpoint, nativePid, started: new Date().toISOString(), errors: [], attempts: [] };
function closeOwnedPopup(optional = false) {
  const script = `Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
public static class PreviewSmokeWindow {
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string klass,string title);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
[DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd,uint msg,IntPtr w,IntPtr l);
}
'@
$previewWindow = [PreviewSmokeWindow]::FindWindow('GreyhoundV2','Greyhound Preview')
if ($previewWindow -eq [IntPtr]::Zero -and ${optional ? "$true" : "$false"}) { exit 0 }
[uint32]$previewProcess = 0
[void][PreviewSmokeWindow]::GetWindowThreadProcessId($previewWindow,[ref]$previewProcess)
if ($previewWindow -eq [IntPtr]::Zero -or $previewProcess -ne ${nativePid}) { throw 'Owned preview window not found' }
[void][PreviewSmokeWindow]::PostMessage($previewWindow,0x10,[IntPtr]::Zero,[IntPtr]::Zero)`;
  execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], { windowsHide: true, stdio: "pipe" });
}
(async () => {
  closeOwnedPopup(true);
  const browser = await chromium.connectOverCDP(endpoint);
  const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes("greyhound.ui") && !p.url().includes("previewWindow"));
  assert(page, "Greyhound main WebView target must exist"); page.setDefaultTimeout(45000);
  page.on("pageerror", e => report.errors.push(e.message));
  await page.waitForFunction(() => typeof Bridge !== "undefined" && Bridge.native);
  await page.evaluate(() => {
    window.previewSmoke = { loads: [], statuses: [], shared: 0, sharedTransfers: new Set(), chunks: 0, commands: [] };
    if (window.previewSmokeInstalled) return;
    window.previewSmokeInstalled = true;
    const load = GreyhoundPreview.Renderer.prototype.load;
    GreyhoundPreview.Renderer.prototype.load = function(v) { const result = load.call(this, v); previewSmoke.loads.push(v.meta); return result; };
    const call = Bridge.call; Bridge.call = function(cmd, args) { previewSmoke.commands.push(cmd); return call.call(Bridge, cmd, args); };
    Bridge.on("preview.status", d => previewSmoke.statuses.push(d)); Bridge.on("preview.chunk", () => previewSmoke.chunks++);
    chrome.webview.addEventListener("sharedbufferreceived", e => { const d = typeof e.additionalData === "string" ? JSON.parse(e.additionalData) : e.additionalData; if (d?.type === "preview") { previewSmoke.shared++; previewSmoke.sharedTransfers.add(d.manifest.transferId); } });
  });
  await page.evaluate(() => setSettings({ showxmodel: "true", showximage: "true" }));
  if (!await page.evaluate(() => S.loaded)) await page.evaluate(() => Bridge.call("game.load"));
  await page.waitForFunction(() => S.loaded && !S.loading, null, { timeout: 120000 });
  report.game = await page.evaluate(() => S.game);
  async function previewType(type) {
    await page.evaluate(async type => { S.type = type; S.text = ""; await query(); }, type);
    const rows = await page.evaluate(() => Bridge.call("assets.rows", { start: 0, count: 100 }));
    assert(rows.length, `${type} rows must be enabled and loaded`);
    const preferred = type === "model" ? process.env.NATIVE_PREVIEW_MODEL : process.env.NATIVE_PREVIEW_IMAGE;
    const indices = rows.map((row, index) => ({ row, index })).filter(({ row }) => !preferred || row.name === preferred)
      .sort((a, b) => Number(a.row.name.startsWith("$")) - Number(b.row.name.startsWith("$"))).map(x => x.index);
    assert(indices.length, `Requested ${type} fixture exists among the first 100 rows`);
    for (const index of indices.slice(0, 25)) {
      if (rows[index].status === "placeholder") continue;
      const before = await page.evaluate(() => previewSmoke.loads.length);
      await page.evaluate(async index => { S.cache.set(0, await Bridge.call("assets.rows", { start: 0, count: 200 })); select(index, false, false, false); select((index + 1) % Math.min(S.view, 100), true, false, false); select(index, false, false, true); await Preview.request(); }, index);
      await page.waitForFunction(before => previewSmoke.loads.length > before || document.querySelector("#previewMessage").classList.contains("error"), before);
      const meta = await page.evaluate(before => previewSmoke.loads.length > before ? previewSmoke.loads.at(-1) : null, before);
      report.attempts.push({ type, index, name: rows[index].name, success: !!meta, info: await page.locator("#previewInfo").textContent(), message: await page.locator("#previewMessage span").textContent() });
      if (!meta) continue;
      assert.equal(meta.kind, type); assert.equal(meta.name, rows[index].name); assert.equal(await page.evaluate(() => S.sel.size), 2);
      assert.equal(await page.locator("#previewCanvas").evaluate(c => c.getContext("webgl2").getError()), 0);
      await page.screenshot({ path: path.join(output, type + ".png") }); return meta;
    }
    throw Error(`No usable ${type} preview among first 25 rows`);
  }
  report.model = await previewType("model");
  const popCount = browser.contexts().flatMap(c => c.pages()).length;
  await page.locator("#previewPopout").click();
  let popup;
  for (let i = 0; i < 100 && !popup; i++) { popup = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes("previewWindow")); if (!popup) await new Promise(r => setTimeout(r, 100)); }
  assert(popup, "Native pop-out WebView must open"); popup.on("pageerror", e => report.errors.push(e.message));
  await popup.waitForFunction(() => document.querySelector("#previewMessage").classList.contains("hidden"), null, { timeout: 45000 });
  report.popout = { title: await popup.locator("#previewName").textContent(), canvas: await popup.locator("#previewCanvas").boundingBox(), pagesBefore: popCount };
  await popup.screenshot({ path: path.join(output, "popout.png") });
  closeOwnedPopup();
  await page.waitForFunction(() => document.querySelector("#previewDetached").classList.contains("hidden") && document.querySelector("#previewMessage").classList.contains("hidden"));
  report.nativeCloseDocks = true;
  report.image = await previewType("image");
  assert(await page.locator("#previewStage").evaluate(el => el.classList.contains("image")));
  await page.evaluate(() => { Preview.request(); select(1, false, false, false); });
  await page.waitForTimeout(300);
  report.newFocusCancels = true;
  await page.evaluate(() => { Preview.request(); Bridge.call("game.clear"); });
  await page.waitForFunction(() => !S.loaded && !S.loading);
  await page.waitForTimeout(300);
  assert.equal(await page.locator("#previewName").textContent(), "Asset preview");
  report.unloadClears = true;
  report.transport = await page.evaluate(() => ({ shared: previewSmoke.sharedTransfers.size, sharedEvents: previewSmoke.shared, chunks: previewSmoke.chunks, loads: new Set(previewSmoke.loads.map(m => m.transferId)).size, exportCommands: previewSmoke.commands.filter(c => c.startsWith("export.")) }));
  assert(report.transport.shared > 0 || report.transport.chunks > 0);
  assert.deepEqual(report.transport.exportCommands, []); assert.deepEqual(report.errors, []);
  report.success = true; report.completed = new Date().toISOString(); fs.writeFileSync(path.join(output, "native-ui-smoke.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ success: true, game: report.game.id, transport: report.transport, model: report.model.name, image: report.image.name, nativeCloseDocks: true, output }));
  // Drop our CDP connection without closing the caller-owned WebView/browser.
  process.exit(0);
})().catch(e => { report.success = false; report.failure = e.stack; fs.writeFileSync(path.join(output, "native-ui-smoke.json"), JSON.stringify(report, null, 2)); console.error(e); process.exit(1); });
