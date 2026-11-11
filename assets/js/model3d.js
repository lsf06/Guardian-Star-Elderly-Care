(function () {
  "use strict";

  var container = document.getElementById("model3d");
  if (!container) return;
  var canvas = document.getElementById("model3dCanvas");
  var fallback = document.getElementById("model3dFallback");
  var note = document.getElementById("modelDemoNote");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function fail() {
    if (canvas) canvas.style.display = "none";
    if (fallback) fallback.hidden = false;
  }
  if (!window.THREE || !canvas) { fail(); return; }
  THREE.ColorManagement.enabled = true;

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: false, powerPreference: "high-performance" });
  } catch (err) { fail(); return; }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0xf3ebdd, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0.78, 4.05);
  camera.lookAt(0, 0, 0);

  /* ---- studio environment ---- */
  function makeEnvironment() {
    var c = document.createElement("canvas");
    c.width = 512; c.height = 256;
    var ctx = c.getContext("2d");
    var g = ctx.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0, "#fbfbf8");
    g.addColorStop(0.42, "#ecebe6");
    g.addColorStop(0.72, "#cfc9be");
    g.addColorStop(1, "#9f9688");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 512, 256);
    var w = ctx.createRadialGradient(150, 80, 5, 150, 80, 150);
    w.addColorStop(0, "rgba(255,252,244,.95)");
    w.addColorStop(1, "rgba(255,252,244,0)");
    ctx.fillStyle = w; ctx.fillRect(0, 0, 512, 256);
    var t = new THREE.CanvasTexture(c);
    t.mapping = THREE.EquirectangularReflectionMapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }
  scene.environment = makeEnvironment();
  if ("environmentIntensity" in scene) scene.environmentIntensity = 0.14;

  var hemi = new THREE.HemisphereLight(0xffffff, 0x8f8a80, 0.35);
  scene.add(hemi);
  var keyLight = new THREE.DirectionalLight(0xffffff, 0.38);
  keyLight.position.set(3.2, 5, 3.8);
  keyLight.castShadow = true;
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.camera.near = 0.5;
  keyLight.shadow.camera.far = 15;
  keyLight.shadow.camera.left = -3.2;
  keyLight.shadow.camera.right = 3.2;
  keyLight.shadow.camera.top = 3.2;
  keyLight.shadow.camera.bottom = -3.2;
  keyLight.shadow.bias = -0.0006;
  scene.add(keyLight);
  var fill = new THREE.DirectionalLight(0xffffff, 0.10);
  fill.position.set(-4, 2.5, 2);
  scene.add(fill);
  var rim = new THREE.PointLight(0xfff6e8, 0.16, 8, 2);
  rim.position.set(0, 2.8, -3);
  scene.add(rim);

  /* ---- floor / contact shadow ---- */
  var floor = new THREE.Mesh(
    new THREE.CircleGeometry(2.4, 64),
    new THREE.ShadowMaterial({ opacity: 0.20 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.195;
  floor.receiveShadow = true;
  scene.add(floor);

  var product = new THREE.Group();
  product.rotation.set(0.05, -0.55, 0);
  scene.add(product);

  /* ---- body ---- */
  function makeBodyTexture() {
    var c = document.createElement("canvas");
    c.width = 16; c.height = 256;
    var ctx = c.getContext("2d");
    var g = ctx.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0.00, "#d9dad7");
    g.addColorStop(0.34, "#d1cec6");
    g.addColorStop(0.46, "#c8c1b4");
    g.addColorStop(0.62, "#beb09b");
    g.addColorStop(0.82, "#b4a58d");
    g.addColorStop(1.00, "#aa9a82");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 16, 256);
    var t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = THREE.RepeatWrapping;
    return t;
  }
  function makeGrain() {
    var c = document.createElement("canvas");
    c.width = 256; c.height = 256;
    var ctx = c.getContext("2d");
    var img = ctx.createImageData(256, 256);
    for (var i = 0; i < img.data.length; i += 4) {
      var v = 155 + Math.floor(Math.random() * 65);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    var t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(3, 3);
    return t;
  }
  var bodyTex = makeBodyTexture();
  var grain = makeGrain();
  var bodyMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    vertexColors: true,
    roughness: 0.74,
    metalness: 0.0,
    bumpMap: grain,
    bumpScale: 0.0018,
    side: THREE.DoubleSide
  });
  var profile = [
    new THREE.Vector2(0.00, 0.200),
    new THREE.Vector2(0.55, 0.200),
    new THREE.Vector2(0.82, 0.198),
    new THREE.Vector2(0.92, 0.192),
    new THREE.Vector2(0.96, 0.175),
    new THREE.Vector2(1.00, 0.115),
    new THREE.Vector2(1.00, -0.050),
    new THREE.Vector2(0.985, -0.120),
    new THREE.Vector2(0.945, -0.165),
    new THREE.Vector2(0.880, -0.188),
    new THREE.Vector2(0.00, -0.188)
  ];
  var bodyGeo = new THREE.LatheGeometry(profile, 128);
  bodyGeo.computeVertexNormals();
  var posAttr = bodyGeo.attributes.position;
  var vcolors = [];
  var cTop = new THREE.Color(0xb0b1ae);
  var cSide = new THREE.Color(0xa08d75);
  for (var vi = 0; vi < posAttr.count; vi++) {
    var vy = posAttr.getY(vi);
    var tt = Math.max(0, Math.min(1, (vy - 0.015) / 0.205));
    var cc = cSide.clone().lerp(cTop, tt);
    vcolors.push(cc.r, cc.g, cc.b);
  }
  bodyGeo.setAttribute("color", new THREE.Float32BufferAttribute(vcolors, 3));
  var body = new THREE.Mesh(bodyGeo, bodyMat);
  body.castShadow = true;
  body.receiveShadow = true;
  product.add(body);

  /* gold seam */
  var seam = new THREE.Mesh(
    new THREE.TorusGeometry(0.996, 0.011, 12, 180),
    new THREE.MeshStandardMaterial({ color: 0xc69d62, metalness: 0.7, roughness: 0.35 })
  );
  seam.rotation.x = Math.PI / 2;
  seam.position.y = 0.055;
  product.add(seam);

  /* photographic top cap + invisible click targets */
  var topTexture = new THREE.TextureLoader().load(window.MODEL_TOP_DATA || "assets/images/model-top.png");
  topTexture.colorSpace = THREE.SRGBColorSpace;
  topTexture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  var topMesh = new THREE.Mesh(
    new THREE.CircleGeometry(0.925, 128),
    new THREE.MeshBasicMaterial({ map: topTexture, transparent: true, side: THREE.DoubleSide, depthWrite: false })
  );
  topMesh.rotation.x = -Math.PI / 2;
  topMesh.rotation.z = Math.PI / 2;
  topMesh.position.y = 0.201;
  topMesh.renderOrder = 2;
  product.add(topMesh);

  var hitMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });
  var keyButton = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.012, 32), hitMat);
  keyButton.position.y = 0.232;
  product.add(keyButton);
  var sosButton = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.012, 32), hitMat);
  sosButton.position.set(0.36, 0.232, 0.20);
  product.add(sosButton);

  /* interaction */
  var raycaster = new THREE.Raycaster();
  var pointer = new THREE.Vector2();
  var dragging = false;
  var lastX = 0, lastY = 0, moved = 0;
  var targetY = -0.55, targetX = 0.05;
  var currentY = targetY, currentX = targetX;
  var pulse = 0, pulseType = "";

  function setNote(name) {
    if (!note) return;
    if (name === "sos") {
      note.textContent = "SOS 演示 · 本地呼救优先，远程通知待联调";
      pulseType = "sos";
    } else {
      note.textContent = "已记录一次确认 · 界面演示，不代表硬件实测";
      pulseType = "confirm";
    }
    pulse = 1;
  }

  canvas.addEventListener("pointerdown", function (e) {
    dragging = true;
    moved = 0;
    lastX = e.clientX;
    lastY = e.clientY;
    try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    var dx = e.clientX - lastX;
    var dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    targetY += dx * 0.008;
    targetX = Math.max(-0.22, Math.min(0.58, targetX + dy * 0.006));
    moved += Math.abs(dx) + Math.abs(dy);
  });
  canvas.addEventListener("pointerup", function (e) {
    if (!dragging) return;
    dragging = false;
    if (moved < 6) {
      var rect = canvas.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      var hits = raycaster.intersectObjects([keyButton, sosButton], true);
      if (hits.length) {
        var obj = hits[0].object;
        setNote(obj === sosButton ? "sos" : "confirm");
      }
    }
  });
  canvas.addEventListener("pointercancel", function () { dragging = false; });

  Array.prototype.forEach.call(document.querySelectorAll("[data-model-action]"), function (btn) {
    btn.addEventListener("click", function () {
      setNote(btn.getAttribute("data-model-action"));
    });
  });

  function resize() {
    var rect = container.getBoundingClientRect();
    if (rect.width < 10 || rect.height < 10) return;
    renderer.setSize(rect.width, rect.height, false);
    camera.aspect = rect.width / rect.height;
    camera.updateProjectionMatrix();
  }
  if ("ResizeObserver" in window) {
    new ResizeObserver(resize).observe(container);
  }
  window.addEventListener("resize", resize);
  window.addEventListener("hashchange", function () { window.setTimeout(resize, 80); });
  resize();

  var last = performance.now();
  function frame(now) {
    var dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    if (!reduceMotion && !dragging) targetY += dt * 0.06;
    currentY += (targetY - currentY) * 0.08;
    currentX += (targetX - currentX) * 0.08;
    product.rotation.y = currentY;
    product.rotation.x = currentX;
    if (pulse > 0) {
      pulse = Math.max(0, pulse - dt * 1.7);
      var s = 1 + Math.sin(pulse * Math.PI) * (pulseType === "sos" ? 0.09 : 0.045);
      if (pulseType === "sos") {
        sosButton.scale.setScalar(s);
      } else {
        keyButton.scale.setScalar(1 - (s - 1) * 0.6);
      }
    } else {
      sosButton.scale.setScalar(1);
      keyButton.scale.setScalar(1);
    }
    renderer.render(scene, camera);
    window.requestAnimationFrame(frame);
  }
  window.requestAnimationFrame(frame);
})();