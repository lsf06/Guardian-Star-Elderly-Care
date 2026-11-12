(function () {
  "use strict";

  var container = document.getElementById("model3d");
  if (!container) return;
  var canvas = document.getElementById("model3dCanvas");
  var fallback = document.getElementById("model3dFallback");
  var note = document.getElementById("modelDemoNote");
  var stageCap = document.querySelector(".model-stage-3d .stage-cap");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function fail() {
    if (canvas) canvas.style.display = "none";
    if (fallback) fallback.hidden = false;
    if (stageCap) stageCap.textContent = "当前浏览器未启用 WebGL，展示静态产品图";
  }
  if (!window.THREE || !canvas) { fail(); return; }

  THREE.ColorManagement.enabled = true;

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  } catch (err) { fail(); return; }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.12;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 1.02, 4.15);
  camera.lookAt(0, 0, 0);

  /* ---- studio environment ---- */
  function makeEnvironment() {
    var c = document.createElement("canvas");
    c.width = 512; c.height = 256;
    var ctx = c.getContext("2d");
    var g = ctx.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0, "#f3ede2");
    g.addColorStop(0.42, "#e8e0d2");
    g.addColorStop(0.72, "#d8d0c0");
    g.addColorStop(1, "#c9c1b1");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 512, 256);
    var w = ctx.createRadialGradient(150, 78, 5, 150, 78, 150);
    w.addColorStop(0, "rgba(255,244,224,.9)");
    w.addColorStop(1, "rgba(255,244,224,0)");
    ctx.fillStyle = w; ctx.fillRect(0, 0, 512, 256);
    var t = new THREE.CanvasTexture(c);
    t.mapping = THREE.EquirectangularReflectionMapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }
  scene.environment = makeEnvironment();
  if ("environmentIntensity" in scene) scene.environmentIntensity = 0.9;

  scene.add(new THREE.HemisphereLight(0xffffff, 0xd8cfc0, 0.9));
  var keyLight = new THREE.DirectionalLight(0xfff2dd, 2.2);
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
  var fill = new THREE.DirectionalLight(0xdfe8ff, 0.7);
  fill.position.set(-4, 2.5, 2);
  scene.add(fill);
  var rim = new THREE.PointLight(0xffc98a, 0.8, 9, 2);
  rim.position.set(-1.8, 2.2, -3);
  scene.add(rim);
  var rimCool = new THREE.PointLight(0x9fd8c6, 0.4, 8, 2);
  rimCool.position.set(2.6, 1.2, -2.4);
  scene.add(rimCool);

  /* ---- floor ---- */
  var floor = new THREE.Mesh(
    new THREE.CircleGeometry(2.4, 64),
    new THREE.ShadowMaterial({ opacity: 0.28 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.195;
  floor.receiveShadow = true;
  scene.add(floor);

  var product = new THREE.Group();
  product.rotation.set(0.06, -0.55, 0);
  scene.add(product);

  /* ---- body ---- */
  function makeGrain() {
    var c = document.createElement("canvas");
    c.width = 256; c.height = 256;
    var ctx = c.getContext("2d");
    var img = ctx.createImageData(256, 256);
    for (var i = 0; i < img.data.length; i += 4) {
      var v = 160 + Math.floor(Math.random() * 60);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    var t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(3, 3);
    return t;
  }
  var grain = makeGrain();

  var profile = [
    new THREE.Vector2(0.00, 0.205),
    new THREE.Vector2(0.55, 0.205),
    new THREE.Vector2(0.80, 0.203),
    new THREE.Vector2(0.90, 0.198),
    new THREE.Vector2(0.95, 0.185),
    new THREE.Vector2(0.99, 0.150),
    new THREE.Vector2(1.00, 0.080),
    new THREE.Vector2(1.00, -0.050),
    new THREE.Vector2(0.985, -0.120),
    new THREE.Vector2(0.945, -0.165),
    new THREE.Vector2(0.880, -0.188),
    new THREE.Vector2(0.00, -0.188)
  ];
  var bodyGeo = new THREE.LatheGeometry(profile, 128);
  bodyGeo.computeVertexNormals();

  var pos = bodyGeo.attributes.position;
  var colors = [];
  var cTop = new THREE.Color(0xd3d2cc);
  var cSide = new THREE.Color(0xbeac92);
  for (var vi = 0; vi < pos.count; vi++) {
    var vy = pos.getY(vi);
    var t = Math.max(0, Math.min(1, (vy - 0.02) / 0.19));
    var cc = cSide.clone().lerp(cTop, t);
    colors.push(cc.r, cc.g, cc.b);
  }
  bodyGeo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));

  var bodyMat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    vertexColors: true,
    roughness: 0.62,
    metalness: 0.0,
    clearcoat: 0.12,
    clearcoatRoughness: 0.55,
    envMapIntensity: 0.6,
    bumpMap: grain,
    bumpScale: 0.0018,
    side: THREE.DoubleSide
  });
  var body = new THREE.Mesh(bodyGeo, bodyMat);
  body.castShadow = true;
  body.receiveShadow = true;
  product.add(body);

  /* gold seam */
  var seam = new THREE.Mesh(
    new THREE.TorusGeometry(0.996, 0.008, 12, 180),
    new THREE.MeshPhysicalMaterial({ color: 0xd9b173, metalness: 0.85, roughness: 0.24, clearcoat: 0.5, emissive: 0x2a1a06, emissiveIntensity: 0.5 })
  );
  seam.rotation.x = Math.PI / 2;
  seam.position.y = 0.075;
  product.add(seam);

  /* ---- central confirm key (geometry only) ---- */
  var keyMat = new THREE.MeshPhysicalMaterial({
    color: 0xd4d2cb,
    roughness: 0.38,
    metalness: 0.04,
    clearcoat: 0.35,
    clearcoatRoughness: 0.36,
    envMapIntensity: 0.55
  });
  var darkMat = new THREE.MeshPhysicalMaterial({
    color: 0x9a958a,
    roughness: 0.48,
    metalness: 0.35,
    envMapIntensity: 0.4
  });

  var keyRecess = new THREE.Mesh(new THREE.CylinderGeometry(0.315, 0.315, 0.008, 96), new THREE.MeshPhysicalMaterial({ color: 0xb1ada4, roughness: 0.55, metalness: 0.1 }));
  keyRecess.position.y = 0.201;
  keyRecess.receiveShadow = true;
  product.add(keyRecess);

  var keyRing = new THREE.Mesh(new THREE.TorusGeometry(0.302, 0.013, 14, 96), darkMat);
  keyRing.rotation.x = Math.PI / 2;
  keyRing.position.y = 0.207;
  keyRing.castShadow = true;
  product.add(keyRing);

  var keyProfile = [
    new THREE.Vector2(0.000, 0.000),
    new THREE.Vector2(0.225, 0.000),
    new THREE.Vector2(0.262, 0.005),
    new THREE.Vector2(0.278, 0.014),
    new THREE.Vector2(0.278, 0.038),
    new THREE.Vector2(0.268, 0.047),
    new THREE.Vector2(0.000, 0.037)
  ];
  var keyGeo = new THREE.LatheGeometry(keyProfile, 96);
  keyGeo.computeVertexNormals();
  var keyButton = new THREE.Mesh(keyGeo, keyMat);
  keyButton.position.y = 0.206;
  keyButton.castShadow = true;
  keyButton.receiveShadow = true;
  product.add(keyButton);

  /* ---- red SOS (geometry only) ---- */
  var sosRecess = new THREE.Mesh(new THREE.CylinderGeometry(0.105, 0.105, 0.008, 48), darkMat);
  sosRecess.position.set(0.42, 0.201, 0.24);
  product.add(sosRecess);
  var sosRing = new THREE.Mesh(new THREE.TorusGeometry(0.094, 0.011, 12, 64), darkMat);
  sosRing.rotation.x = Math.PI / 2;
  sosRing.position.set(0.42, 0.207, 0.24);
  sosRing.castShadow = true;
  product.add(sosRing);

  var sosMat = new THREE.MeshPhysicalMaterial({
    color: 0x9d221b,
    roughness: 0.27,
    metalness: 0.03,
    clearcoat: 0.4,
    clearcoatRoughness: 0.26,
    emissive: 0x2a0302,
    emissiveIntensity: 0.22,
    envMapIntensity: 0.5
  });
  var sosGeo = new THREE.SphereGeometry(0.078, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2);
  sosGeo.scale(1, 0.34, 1);
  var sosButton = new THREE.Mesh(sosGeo, sosMat);
  sosButton.position.set(0.42, 0.219, 0.24);
  sosButton.castShadow = true;
  product.add(sosButton);

  /* ---- interaction ---- */
  var raycaster = new THREE.Raycaster();
  var pointer = new THREE.Vector2();
  var dragging = false;
  var lastX = 0, lastY = 0, moved = 0;
  var targetY = -0.55, targetX = 0.06;
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
    targetX = Math.max(-0.24, Math.min(0.58, targetX + dy * 0.006));
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
        setNote(hits[0].object === sosButton ? "sos" : "confirm");
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
  if ("ResizeObserver" in window) new ResizeObserver(resize).observe(container);
  window.addEventListener("resize", resize);
  window.addEventListener("hashchange", function () { window.setTimeout(resize, 80); });
  resize();

  var last = performance.now();
  function frame(now) {
    var dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    if (!reduceMotion && !dragging) targetY += dt * 0.05;
    currentY += (targetY - currentY) * 0.08;
    currentX += (targetX - currentX) * 0.08;
    product.rotation.y = currentY;
    product.rotation.x = currentX;

    if (pulse > 0) {
      pulse = Math.max(0, pulse - dt * 1.7);
      var s = 1 + Math.sin(pulse * Math.PI) * 0.07;
      if (pulseType === "sos") {
        sosButton.scale.setScalar(s);
        sosMat.emissiveIntensity = 0.22 + pulse * 0.85;
      } else {
        keyButton.scale.setScalar(1 - (s - 1) * 0.45);
        keyMat.emissive.setHex(0x2e2417);
        keyMat.emissiveIntensity = pulse * 0.22;
      }
    } else {
      sosButton.scale.setScalar(1);
      sosMat.emissiveIntensity = 0.22;
      keyButton.scale.setScalar(1);
      keyMat.emissive.setHex(0x000000);
      keyMat.emissiveIntensity = 0;
    }
    renderer.render(scene, camera);
    window.requestAnimationFrame(frame);
  }
  window.requestAnimationFrame(frame);
})();