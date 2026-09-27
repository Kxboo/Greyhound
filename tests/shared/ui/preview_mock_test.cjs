"use strict";
const assert = require("node:assert/strict"), http = require("node:http"), fs = require("node:fs"), path = require("node:path");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "../../../src/WraithXCOD/WraithXCOD/ui");
const server = http.createServer((req, res) => {
  const name = new URL(req.url, "http://localhost").pathname.slice(1) || "index.html", file = path.resolve(root, name);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, bytes) => { if (err) return res.writeHead(404).end(); res.setHeader("Content-Type", ({ ".js": "application/javascript", ".css": "text/css", ".html": "text/html" })[path.extname(file)] || "application/octet-stream"); res.end(bytes); });
});
(async () => {
  await new Promise(r => server.listen(0, "127.0.0.1", r));
  const browser = await chromium.launch({ channel: "msedge", headless: true, args: ["--enable-webgl", "--ignore-gpu-blocklist"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 } }), errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.locator('#libEmpty [data-click="btnLoad"]').click();
    await page.locator('#filters [data-type="model"]').click();
    await page.waitForFunction(() => document.querySelector('.trow[data-i="0"] .name')?.textContent !== "…");
    await page.evaluate(() => { const original = GreyhoundPreview.Renderer.prototype.load; GreyhoundPreview.Renderer.prototype.load = function(value) { window.lastPreview = value.meta; window.lastRenderer = this; return original.call(this, value); }; });
    const row0 = page.locator('.trow[data-i="0"]'), row1 = page.locator('.trow[data-i="1"]');
    await row0.click();
    await page.waitForFunction(() => window.lastPreview?.name === rowAt(0).name);
    await row1.click({ modifiers: ["Control"] });
    await page.waitForFunction(() => window.lastPreview?.name === rowAt(1).name);
    assert.equal(await page.evaluate(() => GreyhoundMock.calls.filter(c => c.cmd === "preview.request").length), 2, "each selection loads automatically");
    assert.equal(await page.evaluate(() => S.sel.size), 2, "preview preserves export selection");
    assert.equal(await page.evaluate(() => GreyhoundMock.calls.findLast(c => c.cmd === "preview.request").args.index), 1);
    assert.deepEqual(await page.evaluate(() => lastPreview.meshes.map(m => m.texture)), [0,1,-1]);
    assert.equal(await page.locator("#previewInfo").textContent(), "6 triangles · LOD 0 · 1 missing textures");
    assert.equal(await page.locator("#libraryWorkspace").getAttribute("data-layout"), "split");
    const stage = await page.locator("#previewCanvas").boundingBox(), oldYaw = await page.evaluate(() => lastRenderer.yaw);
    await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2); await page.mouse.down(); await page.mouse.move(stage.x + stage.width / 2 + 40, stage.y + stage.height / 2 + 20); await page.mouse.up();
    assert.notEqual(await page.evaluate(() => lastRenderer.yaw), oldYaw, "drag orbits the model");
    const distance = await page.evaluate(() => lastRenderer.distance); await page.mouse.wheel(0, -100);
    await page.waitForTimeout(40); assert((await page.evaluate(() => lastRenderer.distance)) < distance, "wheel zooms toward model");
    await page.locator("#previewFit").click(); assert.equal(await page.evaluate(() => lastRenderer.yaw), oldYaw);
    if (process.env.PREVIEW_SCREENSHOT_DIR) { fs.mkdirSync(process.env.PREVIEW_SCREENSHOT_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.PREVIEW_SCREENSHOT_DIR, "model.png") }); }
    // Right-click another selected row must change focus without losing selection.
    await row0.click({ button: "right" }); await page.locator("#menuPreview").click();
    assert.equal(await page.evaluate(() => S.sel.size), 2);
    await page.waitForFunction(() => GreyhoundMock.calls.findLast(c => c.cmd === "preview.request").args.index === 0);
    // Rapid focus changes must load the latest selection instead of a stale model.
    await page.evaluate(() => { select(0, false, false, false); select(1, false, false, false); });
    await page.waitForFunction(() => lastPreview.requestId === GreyhoundMock.calls.findLast(c => c.cmd === "preview.request").args.requestId);
    assert.equal(await page.evaluate(() => lastPreview.name), await page.evaluate(() => rowAt(1).name));
    // Keyboard navigation also loads a row whose virtual page is not cached yet.
    await page.locator("#tbody").press("End");
    await page.waitForFunction(() => rowAt(S.cursor) && lastPreview.name === rowAt(S.cursor).name);
    assert.equal(await page.evaluate(() => S.cursor), await page.evaluate(() => S.view - 1));
    await page.locator("#tbody").press("Home");
    await page.waitForFunction(() => lastPreview.name === rowAt(0).name);
    await page.locator('#layoutBar [data-layout="viewer"]').click();
    assert.equal(await page.locator("#viewerSearchSlot #search").count(), 1);
    await page.setViewportSize({ width: 1100, height: 720 });
    await page.waitForTimeout(80);
    const canvas = await page.locator("#previewCanvas").boundingBox(), list = await page.locator("#libraryList").boundingBox();
    assert(canvas.width > list.width * 2, "viewer allocates most space to canvas");
    await page.locator('#layoutBar [data-layout="split"]').click();
    const divider = await page.locator("#previewDivider").boundingBox();
    await page.mouse.move(divider.x + 5, divider.y + 80); await page.mouse.down(); await page.mouse.move(divider.x - 90, divider.y + 80); await page.mouse.up();
    const share = await page.evaluate(() => Number(S.settings.previewdivider)); assert(share < .5 && share >= .2);
    // Popup uses the retained payload and never queries/changes the library.
    const popupPromise = page.waitForEvent("popup"); await page.locator("#previewPopout").click(); const popup = await popupPromise;
    popup.on("pageerror", e => errors.push(e.message));
    await popup.waitForFunction(() => document.querySelector("#previewMessage").classList.contains("hidden"));
    assert.equal(await popup.evaluate(() => GreyhoundMock.calls.filter(c => c.cmd === "assets.query").length), 0);
    await popup.setViewportSize({ width: 740, height: 540 }); await popup.waitForTimeout(80);
    assert((await popup.locator("#previewCanvas").boundingBox()).width > 680);
    await row1.click();
    const popoutAsset = await page.evaluate(() => rowAt(1).name);
    await popup.waitForFunction(name => document.querySelector("#previewName").textContent === name, popoutAsset);
    await popup.close(); await page.waitForFunction(() => document.querySelector("#previewDetached").classList.contains("hidden"));
    await page.waitForFunction(name => document.querySelector("#previewName").textContent === name, popoutAsset);
    await page.locator('#filters [data-type="image"]').click();
    await page.waitForFunction(() => rowAt(0)?.type === "image"); await row0.click();
    await page.waitForFunction(() => window.lastPreview?.kind === "image");
    assert(await page.locator("#previewStage").evaluate(el => el.classList.contains("image")));
    await page.waitForTimeout(60);
    assert.equal(await page.locator("#previewCanvas").evaluate(c => c.getContext("webgl2").getError()), 0, "renderer should not produce GL errors");
    if (process.env.PREVIEW_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.PREVIEW_SCREENSHOT_DIR, "image.png") });
    await page.locator("#previewZoomIn").click(); await page.locator("#previewFit").click();
    await page.evaluate(() => { window.lostExtension = lastRenderer.gl.getExtension("WEBGL_lose_context"); lostExtension?.loseContext(); });
    if (await page.evaluate(() => !!window.lostExtension)) {
      await page.waitForFunction(() => lastRenderer.lost);
      await page.evaluate(() => lostExtension.restoreContext());
      await page.waitForFunction(() => !lastRenderer.lost && document.querySelector("#previewMessage").classList.contains("hidden"));
      assert.equal(await page.evaluate(() => lastRenderer.gl.getError()), 0, "context restoration reloads the retained asset");
    }
    // Unload overtakes a newly requested decode.
    await row1.click(); await page.locator("#btnClear").click(); await page.waitForTimeout(350);
    assert.equal(await page.locator("#previewName").textContent(), "Asset preview");
    assert.equal(await page.locator("#previewMessage span").textContent(), "Select a model or image to preview it.");
    await page.reload(); await page.waitForFunction(() => !!S.settings.previewlayout);
    assert.equal(await page.locator("#libraryWorkspace").getAttribute("data-layout"), "split");
    assert.equal(await page.evaluate(() => Number(S.settings.previewdivider)), share);
    assert.deepEqual(errors, [], "No browser exceptions");
    console.log("Preview UI mock: passed automatic loading on click/keyboard/multiselect, duplicate slots/missing textures, stale requests, layout/divider persistence, resizing, popout-close docking, image controls and unload.");
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });
