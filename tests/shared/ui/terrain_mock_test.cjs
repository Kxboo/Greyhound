"use strict";
const assert = require("node:assert/strict"), http = require("node:http"), fs = require("node:fs"), path = require("node:path");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "../../../src/WraithXCOD/WraithXCOD/ui");
const server = http.createServer((req, res) => {
  const name = new URL(req.url, "http://localhost").pathname.slice(1) || "index.html", file = path.resolve(root, name);
  if (!file.startsWith(root + path.sep)) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, bytes) => {
    if (err) return res.writeHead(404).end();
    res.setHeader("Content-Type", ({ ".js": "application/javascript", ".css": "text/css", ".html": "text/html" })[path.extname(file)] || "application/octet-stream");
    res.end(bytes);
  });
});
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage(), errors = [];
    page.on("pageerror", e => errors.push(String(e)));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.locator('[data-page="settings"]').click();
    const area = page.locator("#set-terrain .row").filter({ hasText: "Cold War area" });
    const format = page.locator("#set-terrain .row").filter({ hasText: "Cold War format" });
    const note = page.locator("#set-terrain .row").filter({ hasText: "Terrain and decals" });
    const setGame = async (id, extra = {}) => {
      await page.evaluate(({ id, extra }) => GreyhoundMock.receive("state", {
        loaded: true, game: { id, name: id, ...extra }, total: 1,
      }), { id, extra });
      await page.waitForFunction(id => document.querySelector("#gameName").textContent === id, id);
    };
    await setGame("black_ops_cw");
    assert(await area.isVisible());
    assert(await format.isVisible());
    assert.match(await note.textContent(), /terrain material layers are included; separate decals are omitted/);
    await area.getByRole("button", { name: "5 × 5 tiles near the camera" }).click();
    await setGame("black_ops_4");
    assert(!(await area.isVisible()), "CW area cannot imply BO4 nearby support");
    assert(!(await format.isVisible()), "CW formats cannot imply a BO4 baked exporter");
    assert.match(await note.textContent(), /BO4: use Diagnostics/);
    const decals = page.locator("#set-decals");
    const output = decals.locator(".row").filter({ hasText: "Decal output" });
    assert(await output.getByRole("button", { name: "Reusable asset", exact: true }).evaluate(b => b.classList.contains("on")), "placements must be opt-in");
    await output.getByRole("button", { name: "Asset + original placements", exact: true }).click();
    assert.equal(await page.evaluate(() => S.settings.decalplacements), "true");
    assert.match(await decals.textContent(), /Cold War decals use a different format/);
    assert.match(await page.locator("#set-library").textContent(), /Decals/);
    await page.locator('[data-page="diagnostics"]').click();
    const capture = page.locator('[data-tool="terrainSource"]');
    assert(!(await capture.isDisabled()), "BO4 retains its own source route");
    await setGame("black_ops_cw");
    assert(!(await capture.isDisabled()), "CW source route remains available");
    await page.locator('[data-page="settings"]').click();
    assert(await area.isVisible());
    assert.equal(await page.evaluate(() => S.settings.decalplacements), "true", "game switching preserves the independent decal choice");
    assert(await area.locator('button[data-v="nearby"]').evaluate(b => b.classList.contains("on")), "switching games must preserve CW settings");
    await setGame("black_ops_3");
    assert(!(await area.isVisible()));
    assert(await capture.isDisabled());
    await setGame("black_ops_cw", { file: true });
    assert(await capture.isDisabled(), "package preview is not a live map");
    assert.deepEqual(errors, []);
    console.log("Terrain UI: separate BO4/CW routes, decal scope and preserved CW settings passed");
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); process.exitCode = 1; server.close(); });
