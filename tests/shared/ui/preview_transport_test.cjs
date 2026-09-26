"use strict";
const assert = require("node:assert/strict");
const { Assembler, validate, MAX_BYTES } = require("../../../src/WraithXCOD/WraithXCOD/ui/preview.js");
function fixture() {
  const buffer = new ArrayBuffer(124), f = new Float32Array(buffer);
  for (let i = 0; i < 3; i++) { f.set([i, 0, 0, 0, 0, 1, 0, 0], i * 9); new Uint8Array(buffer).fill(255, i * 36 + 32, i * 36 + 36); }
  new Uint32Array(buffer, 108, 3).set([0, 1, 2]);
  new Uint8Array(buffer, 120, 4).set([250, 80, 40, 128]);
  return { meta: { requestId: 1, generation: 7, transferId: 1, kind: "model", byteLength: 124, meshes: [{ vertexOffset: 0, vertexCount: 3, indexOffset: 108, indexCount: 3, texture: 0, materialName: "duplicate" }, { vertexOffset: 0, vertexCount: 3, indexOffset: 108, indexCount: 3, texture: -1, materialName: "duplicate" }], textures: [{ offset: 120, width: 1, height: 1 }] }, buffer };
}
const results = [], errors = [], assembler = new Assembler(v => results.push(v), e => errors.push(e.message));
const { meta, buffer } = fixture();
assembler.expect(1, 7);
assert.equal(assembler.accept("begin", { ...meta, generation: 6 }), false);
assembler.accept("begin", meta);
assert.equal(assembler.accept("chunk", { ...meta, transferId: 0, offset: 0, data: "AAAA" }), false);
assembler.accept("chunk", { ...meta, offset: 0, data: Buffer.from(buffer).toString("base64") });
assembler.accept("end", meta);
assert.equal(results.length, 1);
assert.deepEqual(results[0].meta.meshes.map(m => m.texture), [0, -1], "material names must not merge texture slots");
assert.equal(new Uint8Array(results[0].buffer)[123], 128, "usable alpha preserved");
assembler.expect(2, 7); assembler.accept("begin", { ...meta, requestId: 2 }); assembler.cancel();
assert.equal(assembler.accept("end", { ...meta, requestId: 2 }), false, "unload must reject pending completion");
assembler.expect(3, 8); assembler.accept("begin", { ...meta, requestId: 3, generation: 8, byteLength: MAX_BYTES + 1 });
assert.match(errors.pop(), /size/);
assembler.expect(1, 7); assembler.accept("begin", meta); assembler.accept("chunk", { ...meta, offset: 4, data: "AAAA" });
assert.match(errors.pop(), /chunk/);
assert.throws(() => validate({ ...meta, meshes: [] }, buffer), /usable geometry/);
assert.throws(() => validate({ ...meta, meshes: [{ ...meta.meshes[0], texture: 44 }] }, buffer), /texture slot/);
const broken = fixture(); new Uint32Array(broken.buffer, 108, 3)[2] = 3;
assert.throws(() => validate(broken.meta, broken.buffer), /outside/);
const image = { ...meta, kind: "image", meshes: [] };
assert.equal(validate(image, buffer).meta.textures[0].width, 1);
assert.throws(() => validate({ ...image, textures: [{ offset: 124, width: 1, height: 1 }] }, buffer), /range/);
assembler.expect(8, 9); assert.equal(assembler.shared({ ...image, requestId: 8, generation: 9 }, buffer), true);
assert.equal(results.length, 2);
console.log("Preview transport: passed slot binding, alpha, stale generations/replays, cancellation, image spans and bounds.");
