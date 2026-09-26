// Bounded preview transport and a dependency-free, demand-rendered WebGL viewer.
// The material/texture slot belongs to a submesh, never to a material name.
(function (root) {
  "use strict";
  const MAX_BYTES = 256 * 1024 * 1024, MAX_CHUNK = 256 * 1024;
  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
  function bounded(n, max, label) {
    if (!Number.isSafeInteger(n) || n < 0 || n > max) throw Error("Invalid preview " + label);
    return n;
  }
  function validate(meta, buffer) {
    const size = bounded(meta.byteLength, MAX_BYTES, "size");
    if (buffer.byteLength !== size) throw Error("Incomplete preview buffer");
    const span = (offset, count, stride) => {
      bounded(offset, size, "offset"); bounded(count, MAX_BYTES, "count");
      if (offset + count * stride > size) throw Error("Preview buffer range exceeds its size");
    };
    if (!["model", "image"].includes(meta.kind)) throw Error("Unsupported preview type");
    const textures = meta.textures || [], meshes = meta.meshes || [];
    if (textures.length > 4096 || meshes.length > 65536) throw Error("Preview has too many parts");
    textures.forEach(t => {
      bounded(t.width, 4096, "texture width"); bounded(t.height, 4096, "texture height");
      if (!t.width || !t.height) throw Error("Empty preview texture");
      span(t.offset, t.width * t.height, 4);
    });
    meshes.forEach(m => {
      span(m.vertexOffset, m.vertexCount, 36); span(m.indexOffset, m.indexCount, 4);
      if (m.vertexOffset % 4 || m.indexOffset % 4 || m.indexCount % 3) throw Error("Misaligned preview geometry");
      if (m.texture !== -1 && (!Number.isInteger(m.texture) || m.texture < 0 || m.texture >= textures.length)) throw Error("Invalid preview texture slot");
      const indices = new Uint32Array(buffer, m.indexOffset, m.indexCount);
      for (const i of indices) if (i >= m.vertexCount) throw Error("Preview index is outside its submesh");
      const vertices = new Float32Array(buffer, m.vertexOffset, m.vertexCount * 9);
      for (let i = 0; i < vertices.length; i += 9) for (let j = 0; j < 8; j++) {
        if (!Number.isFinite(vertices[i + j])) throw Error("Preview contains non-finite geometry");
      }
    });
    if (meta.kind === "model" && !meshes.some(m => m.indexCount)) throw Error("This model has no usable geometry");
    if (meta.kind === "image" && !textures.length) throw Error("This image could not be decoded");
    return { meta, buffer };
  }
  class Assembler {
    constructor(onReady, onError) { this.onReady = onReady; this.onError = onError; this.cancel(); }
    cancel() { this.requestId = null; this.generation = null; this.meta = null; this.bytes = null; this.next = 0; }
    expect(requestId, generation) { this.cancel(); this.requestId = requestId; this.generation = generation; }
    matches(data) { return data.requestId === this.requestId && data.generation === this.generation; }
    accept(kind, data) {
      if (!this.matches(data)) return false;
      try {
        if (kind === "begin") {
          this.meta = data; this.bytes = new Uint8Array(bounded(data.byteLength, MAX_BYTES, "size")); this.next = 0;
        } else if (kind === "chunk") {
          if (data.transferId !== this.meta?.transferId) return false;
          if (!this.bytes || data.offset !== this.next || typeof data.data !== "string" || data.data.length > MAX_CHUNK * 4 / 3 + 4) throw Error("Invalid preview chunk");
          const decoded = atob(data.data);
          if (decoded.length > MAX_CHUNK || this.next + decoded.length > this.bytes.length) throw Error("Preview chunk exceeds its bound");
          for (let i = 0; i < decoded.length; i++) this.bytes[this.next + i] = decoded.charCodeAt(i);
          this.next += decoded.length;
        } else if (kind === "end") {
          if (data.transferId !== this.meta?.transferId) return false;
          if (!this.bytes || this.next !== this.bytes.length) throw Error("Incomplete preview transfer");
          const value = validate(this.meta, this.bytes.buffer);
          this.bytes = null; this.meta = null; this.onReady(value);
        }
      } catch (e) { this.bytes = null; this.meta = null; this.onError(e); }
      return true;
    }
    shared(meta, buffer) {
      if (!this.matches(meta)) return false;
      this.bytes = null; this.meta = null; this.next = 0;
      try { this.onReady(validate(meta, buffer)); } catch (e) { this.onError(e); }
      return true;
    }
  }
  function multiply(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
    return o;
  }
  function perspective(aspect, near, far) {
    const f = 1 / Math.tan(Math.PI / 8), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  }
  const normalize = a => { const n = Math.hypot(...a) || 1; return a.map(v => v / n); };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a.reduce((v, n, i) => v + n * b[i], 0);
  function viewMatrix(eye, target) {
    const z = normalize(eye.map((n, i) => n - target[i])), x = normalize(cross([0, 0, 1], z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  }
  class Renderer {
    constructor(canvas, onError = () => {}) {
      this.canvas = canvas; this.onError = onError; this.parts = []; this.textures = []; this.kind = ""; this.pending = false; this.imageZoom = 1; this.pan = [0, 0];
      this.gl = canvas.getContext("webgl2", { alpha: true, antialias: true, premultipliedAlpha: false });
      if (!this.gl) throw Error("The preview requires WebGL 2. Enable hardware acceleration or update the WebView runtime.");
      this.initialize = () => {
      const gl = this.gl;
      const shader = (type, code) => { const s = gl.createShader(type); gl.shaderSource(s, code); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s)); return s; };
      const vs = shader(gl.VERTEX_SHADER, `#version 300 es
        precision highp float; layout(location=0) in vec3 position; layout(location=1) in vec3 normal; layout(location=2) in vec2 uv; layout(location=3) in vec4 color;
        uniform mat4 matrix; uniform bool imageMode; uniform vec2 imageScale; uniform vec2 imagePan; out vec2 texUV; out vec4 tint; out vec3 n;
        void main(){ gl_Position=imageMode?vec4(position.xy*imageScale+imagePan,0.,1.):matrix*vec4(position,1.); texUV=uv; tint=color; n=normal; }`);
      const fs = shader(gl.FRAGMENT_SHADER, `#version 300 es
        precision highp float; in vec2 texUV; in vec4 tint; in vec3 n; uniform sampler2D diffuse; uniform bool textured; uniform bool imageMode; out vec4 frag;
        void main(){ vec4 c=(textured?texture(diffuse,texUV):vec4(.68,.69,.71,1.)); c.rgb*=tint.rgb; if(c.a<.015)discard;
        float light=imageMode?1.:.48+.52*max(0.,dot(normalize(n),normalize(vec3(.4,-.55,.8)))); frag=vec4(c.rgb*light,c.a); }`);
      this.program = gl.createProgram(); gl.attachShader(this.program, vs); gl.attachShader(this.program, fs); gl.linkProgram(this.program); gl.deleteShader(vs); gl.deleteShader(fs);
      if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(this.program));
      this.uniforms = Object.fromEntries(["matrix", "imageMode", "imageScale", "imagePan", "diffuse", "textured"].map(n => [n, gl.getUniformLocation(this.program, n)]));
      };
      this.initialize();
      canvas.addEventListener("contextmenu", e => e.preventDefault());
      canvas.addEventListener("pointerdown", e => { canvas.focus(); canvas.setPointerCapture(e.pointerId); this.drag = { x: e.clientX, y: e.clientY, pan: e.button !== 0 || e.shiftKey }; });
      canvas.addEventListener("pointerup", () => { this.drag = null; });
      canvas.addEventListener("pointercancel", () => { this.drag = null; });
      canvas.addEventListener("pointermove", e => {
        if (!this.drag) return;
        const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y; this.drag.x = e.clientX; this.drag.y = e.clientY;
        if (this.kind === "image") { this.pan[0] += dx; this.pan[1] += dy; }
        else if (this.drag.pan) {
          const k = this.distance * .82 / Math.max(1, canvas.clientHeight), right = [-Math.sin(this.yaw), Math.cos(this.yaw), 0];
          const up = [-Math.sin(this.pitch) * Math.cos(this.yaw), -Math.sin(this.pitch) * Math.sin(this.yaw), Math.cos(this.pitch)];
          this.target = this.target.map((v, i) => v - dx * k * right[i] + dy * k * up[i]);
        } else { this.yaw -= dx * .009; this.pitch = clamp(this.pitch + dy * .009, -1.5, 1.5); }
        this.schedule();
      });
      canvas.addEventListener("wheel", e => { e.preventDefault(); this.zoom(Math.exp(-clamp(e.deltaY, -150, 150) * .005)); }, { passive: false });
      canvas.addEventListener("keydown", e => {
        if (e.key.toLowerCase() === "f") { e.preventDefault(); this.fit(); }
        if (["+", "="].includes(e.key)) { e.preventDefault(); this.zoom(1.2); }
        if (e.key === "-") { e.preventDefault(); this.zoom(1 / 1.2); }
      });
      canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); this.lost = true; onError(Error("Preview graphics were reset. Select Preview again to reload.")); });
      canvas.addEventListener("webglcontextrestored", () => {
        this.lost = false; this.parts = []; this.textures = []; this.kind = "";
        try { this.initialize(); canvas.dispatchEvent(new Event("previewrestore")); } catch (e) { onError(e); }
      });
      this.observer = new ResizeObserver(() => this.schedule()); this.observer.observe(canvas);
    }
    clear() {
      const gl = this.gl;
      for (const p of this.parts) { gl.deleteVertexArray(p.vao); gl.deleteBuffer(p.vertices); gl.deleteBuffer(p.indices); }
      for (const t of this.textures) gl.deleteTexture(t);
      this.parts = []; this.textures = []; this.kind = ""; this.schedule();
    }
    part(vertices, indices, texture) {
      const gl = this.gl, vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      const vb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vb); gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
      for (const [location, size, type, norm, offset] of [[0,3,gl.FLOAT,false,0],[1,3,gl.FLOAT,false,12],[2,2,gl.FLOAT,false,24],[3,4,gl.UNSIGNED_BYTE,true,32]]) {
        gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location, size, type, norm, 36, offset);
      }
      const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
      this.parts.push({ vao, vertices: vb, indices: ib, count: indices.length, texture });
    }
    load(value) {
      this.clear(); const { meta, buffer } = value, gl = this.gl; this.kind = meta.kind;
      this.textures = (meta.textures || []).map(t => {
        const texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, t.width, t.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(buffer, t.offset, t.width * t.height * 4));
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, meta.kind === "image" ? gl.CLAMP_TO_EDGE : gl.REPEAT); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, meta.kind === "image" ? gl.CLAMP_TO_EDGE : gl.REPEAT);
        return texture;
      });
      this.min = [Infinity, Infinity, Infinity]; this.max = [-Infinity, -Infinity, -Infinity];
      if (meta.kind === "image") {
        const v = new ArrayBuffer(4 * 36), f = new Float32Array(v), bytes = new Uint8Array(v);
        [[-1,-1,0,1],[1,-1,1,1],[1,1,1,0],[-1,1,0,0]].forEach((p, i) => { f.set([p[0],p[1],0,0,0,1,p[2],p[3]], i * 9); bytes.fill(255, i * 36 + 32, i * 36 + 36); });
        this.part(new Uint8Array(v), new Uint32Array([0,1,2,0,2,3]), 0); this.imageWidth = meta.textures[0].width; this.imageHeight = meta.textures[0].height;
      } else for (const m of meta.meshes) {
        this.part(new Uint8Array(buffer, m.vertexOffset, m.vertexCount * 36), new Uint32Array(buffer, m.indexOffset, m.indexCount), m.texture);
        const f = new Float32Array(buffer, m.vertexOffset, m.vertexCount * 9);
        for (let i = 0; i < f.length; i += 9) for (let k = 0; k < 3; k++) { this.min[k] = Math.min(this.min[k], f[i + k]); this.max[k] = Math.max(this.max[k], f[i + k]); }
      }
      gl.bindVertexArray(null); this.fit();
    }
    fit() {
      this.pan = [0, 0]; this.imageZoom = 1; this.yaw = -.8; this.pitch = .35;
      if (this.kind === "image") { this.schedule(); return; }
      this.target = this.min ? this.min.map((v, i) => (v + this.max[i]) / 2) : [0, 0, 0];
      this.radius = this.min ? Math.max(.001, Math.hypot(...this.min.map((v, i) => this.max[i] - v)) / 2) : 1;
      const aspect = this.canvas.clientWidth / Math.max(1, this.canvas.clientHeight), halfFov = Math.atan(Math.tan(Math.PI / 8) * Math.min(1, aspect));
      this.distance = this.radius / Math.sin(halfFov) * 1.12; this.schedule();
    }
    zoom(factor) { if (this.kind === "image") this.imageZoom = clamp(this.imageZoom * factor, .02, 64); else this.distance = clamp(this.distance / factor, this.radius * .015, this.radius * 1000); this.schedule(); }
    schedule() { if (!this.pending) { this.pending = true; requestAnimationFrame(() => { this.pending = false; try { this.draw(); } catch (e) { this.onError(e); } }); } }
    draw() {
      if (this.lost) return;
      const gl = this.gl, c = this.canvas, dpr = Math.min(2, window.devicePixelRatio || 1), w = Math.round(c.clientWidth * dpr), h = Math.round(c.clientHeight * dpr);
      if (!w || !h) return;
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); if (!this.parts.length) return;
      gl.useProgram(this.program); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.disable(gl.CULL_FACE);
      gl.uniform1i(this.uniforms.diffuse, 0); gl.uniform1i(this.uniforms.imageMode, this.kind === "image");
      if (this.kind === "image") {
        gl.disable(gl.DEPTH_TEST); const scale = Math.min(c.clientWidth / this.imageWidth, c.clientHeight / this.imageHeight) * .92 * this.imageZoom;
        gl.uniform2f(this.uniforms.imageScale, this.imageWidth * scale / c.clientWidth, this.imageHeight * scale / c.clientHeight);
        gl.uniform2f(this.uniforms.imagePan, this.pan[0] * 2 / c.clientWidth, -this.pan[1] * 2 / c.clientHeight);
      } else {
        gl.enable(gl.DEPTH_TEST); const cp = Math.cos(this.pitch), eye = this.target.map((v, i) => v + this.distance * [cp * Math.cos(this.yaw), cp * Math.sin(this.yaw), Math.sin(this.pitch)][i]);
        const matrix = multiply(perspective(w / h, Math.max(.00001, this.distance / 10000), this.distance + this.radius * 20), viewMatrix(eye, this.target));
        gl.uniformMatrix4fv(this.uniforms.matrix, false, matrix);
      }
      for (const p of this.parts) { gl.bindVertexArray(p.vao); gl.uniform1i(this.uniforms.textured, p.texture >= 0); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, p.texture >= 0 ? this.textures[p.texture] : null); gl.drawElements(gl.TRIANGLES, p.count, gl.UNSIGNED_INT, 0); }
      gl.bindVertexArray(null);
    }
    destroy() { this.clear(); this.observer.disconnect(); this.gl.deleteProgram(this.program); }
  }
  const api = { Assembler, Renderer, validate, clamp, MAX_BYTES, MAX_CHUNK };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GreyhoundPreview = api;
})(typeof window === "undefined" ? globalThis : window);
