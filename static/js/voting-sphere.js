/*
 * Strawpoll — rotating 3D voting sphere (home page hero).
 *
 * A single lightweight scene, no external models:
 *   * a wireframe icosahedron core with an inner glow,
 *   * "vote dots" distributed on a fibonacci sphere (like ballots on a globe),
 *   * two orbit rings with travelling satellites,
 *   * a particle starfield and floating background shapes.
 *
 * Behaviour:
 *   * Lazy: the script only loads on the home page (deferred) and the scene
 *     starts after the page is interactive.
 *   * Pauses rendering when the tab is hidden or the hero scrolls out of view.
 *   * Caps devicePixelRatio at 2 and reduces particle counts on small screens.
 *   * Pointer parallax: the whole group leans toward the cursor.
 *   * Fallback: if WebGL is unavailable, Three.js failed to load, or the user
 *     prefers reduced motion, the canvas stays hidden and the pure-CSS orb
 *     remains — no broken visuals, no wasted battery.
 */
(function () {
  'use strict';

  var canvas = document.getElementById('voting-sphere');
  if (!canvas) return;

  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function webglOK() {
    try {
      var test = document.createElement('canvas');
      return !!(window.WebGLRenderingContext &&
        (test.getContext('webgl') || test.getContext('experimental-webgl')));
    } catch (err) {
      return false;
    }
  }

  if (reduceMotion || !webglOK() || typeof THREE === 'undefined') {
    return; // the .orb-fallback in the markup remains visible
  }

  var host = canvas.parentElement;
  var isSmall = window.innerWidth < 768;

  /* --- Renderer / scene / camera ------------------------------------------ */
  var renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  renderer.setClearColor(0x000000, 0); // transparent: the page aurora shows through
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 7.4);

  var world = new THREE.Group(); // everything lives here; parallax leans this
  scene.add(world);

  var COLORS = { blue: 0x3b82f6, cyan: 0x22d3ee, purple: 0xa855f7, violet: 0x8b5cf6, ice: 0x7dd3fc };

  /* --- Core: wireframe icosahedra + inner glow ------------------------------ */
  var core = new THREE.Group();

  var shellOuter = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.42, 1),
    new THREE.MeshBasicMaterial({ color: COLORS.blue, wireframe: true, transparent: true, opacity: 0.38 })
  );
  var shellInner = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.02, 1),
    new THREE.MeshBasicMaterial({ color: COLORS.purple, wireframe: true, transparent: true, opacity: 0.24 })
  );
  var glowSphere = new THREE.Mesh(
    new THREE.SphereGeometry(0.58, 32, 32),
    new THREE.MeshBasicMaterial({ color: COLORS.cyan, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending })
  );
  core.add(shellOuter, shellInner, glowSphere);
  world.add(core);

  /* --- Vote dots on a fibonacci sphere --------------------------------------- */
  var dots = [];
  var DOT_COUNT = 26;
  var golden = Math.PI * (3 - Math.sqrt(5));
  var dotColors = [COLORS.cyan, COLORS.blue, COLORS.purple];
  for (var i = 0; i < DOT_COUNT; i++) {
    var y = 1 - (i / (DOT_COUNT - 1)) * 2;
    var radiusAtY = Math.sqrt(Math.max(0, 1 - y * y));
    var theta = golden * i;
    var dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.065, 16, 16),
      new THREE.MeshBasicMaterial({ color: dotColors[i % dotColors.length] })
    );
    dot.position.set(Math.cos(theta) * radiusAtY, y, Math.sin(theta) * radiusAtY).multiplyScalar(1.42);
    dot.userData.phase = Math.random() * Math.PI * 2;
    dots.push(dot);
    core.add(dot);
  }

  /* --- Orbit rings + satellites ----------------------------------------------- */
  function ring(radius, color, opacity, tiltX, tiltZ) {
    var mesh = new THREE.Mesh(
      new THREE.TorusGeometry(radius, 0.012, 8, 128),
      new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: opacity })
    );
    mesh.rotation.x = tiltX;
    mesh.rotation.z = tiltZ;
    world.add(mesh);
    return mesh;
  }
  var ringA = ring(2.05, COLORS.blue, 0.4, 1.18, 0.35);
  var ringB = ring(2.42, COLORS.purple, 0.28, -1.05, -0.5);

  var satA = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 16), new THREE.MeshBasicMaterial({ color: COLORS.cyan }));
  var satB = new THREE.Mesh(new THREE.SphereGeometry(0.06, 16, 16), new THREE.MeshBasicMaterial({ color: 0xf0abfc }));
  world.add(satA, satB);

  /* --- Particle starfield ------------------------------------------------------- */
  var PARTICLES = isSmall ? 320 : 700;
  var positions = new Float32Array(PARTICLES * 3);
  for (var p = 0; p < PARTICLES; p++) {
    var r = 4 + Math.random() * 6;
    var phi = Math.acos(2 * Math.random() - 1);
    var lambda = Math.random() * Math.PI * 2;
    positions[p * 3] = r * Math.sin(phi) * Math.cos(lambda);
    positions[p * 3 + 1] = r * Math.sin(phi) * Math.sin(lambda) * 0.7;
    positions[p * 3 + 2] = r * Math.cos(phi) - 2;
  }
  var particleGeo = new THREE.BufferGeometry();
  particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  var particleField = new THREE.Points(particleGeo, new THREE.PointsMaterial({
    color: COLORS.ice, size: 0.035, transparent: true, opacity: 0.55,
  }));
  world.add(particleField);

  /* --- Floating background shapes -------------------------------------------------- */
  var floaters = [];
  var SHAPE_COUNT = isSmall ? 4 : 7;
  var shapeGeos = [
    new THREE.IcosahedronGeometry(0.42, 0),
    new THREE.OctahedronGeometry(0.36, 0),
    new THREE.TorusGeometry(0.3, 0.1, 8, 24),
    new THREE.TetrahedronGeometry(0.4, 0),
  ];
  var shapeColors = [COLORS.blue, COLORS.purple, COLORS.cyan, COLORS.violet];
  for (var s = 0; s < SHAPE_COUNT; s++) {
    var mesh = new THREE.Mesh(
      shapeGeos[s % shapeGeos.length],
      new THREE.MeshBasicMaterial({
        color: shapeColors[s % shapeColors.length],
        wireframe: s % 2 === 0,
        transparent: true,
        opacity: 0.22 + (s % 3) * 0.06,
      })
    );
    mesh.position.set(
      (Math.random() - 0.5) * 9,
      (Math.random() - 0.5) * 4.6,
      -1.5 - Math.random() * 3.5
    );
    mesh.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
    mesh.userData = {
      rotX: (Math.random() - 0.5) * 0.5,
      rotY: (Math.random() - 0.5) * 0.6,
      bobAmp: 0.18 + Math.random() * 0.25,
      bobPhase: Math.random() * Math.PI * 2,
      baseY: mesh.position.y,
    };
    floaters.push(mesh);
    world.add(mesh);
  }

  /* --- Layout: keep the sphere clear of the headline on wide screens ------- */
  function layout() {
    var w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    // Keep the sphere clear of the headline whenever the hero is wide enough.
    var wide = w >= 600;
    world.position.x = wide ? 2.0 : 0;
    world.position.y = wide ? 0 : 0.55;
  }
  layout();
  window.addEventListener('resize', layout);

  /* --- Pointer parallax ------------------------------------------------------ */
  var targetX = 0, targetY = 0;
  window.addEventListener('pointermove', function (e) {
    targetX = (e.clientY / window.innerHeight - 0.5) * -0.28;
    targetY = (e.clientX / window.innerWidth - 0.5) * 0.34;
  }, { passive: true });

  /* --- Render loop (pausable) -------------------------------------------------- */
  var clock = new THREE.Clock();
  var running = false;
  var heroVisible = true;
  var started = false;

  function render() {
    var dt = Math.min(clock.getDelta(), 0.05);
    var t = clock.elapsedTime;

    core.rotation.y += dt * 0.22;
    core.rotation.x = Math.sin(t * 0.3) * 0.12;
    shellInner.rotation.y -= dt * 0.4;
    shellInner.rotation.z += dt * 0.18;
    glowSphere.scale.setScalar(1 + Math.sin(t * 1.6) * 0.08);

    dots.forEach(function (dot) {
      dot.scale.setScalar(1 + Math.sin(t * 2 + dot.userData.phase) * 0.28);
    });

    ringA.rotation.z += dt * 0.12;
    ringB.rotation.z -= dt * 0.09;
    var aA = t * 0.55, aB = -t * 0.4;
    satA.position.set(Math.cos(aA) * 2.05, Math.sin(aA) * 2.05 * Math.sin(1.18) * 0.9, Math.sin(aA) * 2.05 * Math.cos(1.18) * 0.9);
    satB.position.set(Math.cos(aB) * 2.42, Math.sin(aB) * 2.42 * Math.sin(-1.05) * 0.9, Math.sin(aB) * 2.42 * Math.cos(-1.05) * 0.9);

    particleField.rotation.y += dt * 0.02;

    floaters.forEach(function (mesh) {
      mesh.rotation.x += mesh.userData.rotX * dt;
      mesh.rotation.y += mesh.userData.rotY * dt;
      mesh.position.y = mesh.userData.baseY + Math.sin(t * 0.6 + mesh.userData.bobPhase) * mesh.userData.bobAmp;
    });

    world.rotation.x += (targetX - world.rotation.x) * 0.04;
    world.rotation.y += (targetY - world.rotation.y) * 0.04;

    renderer.render(scene, camera);
  }

  function loop() {
    if (!running) return;
    render();
    requestAnimationFrame(loop);
  }

  function start() {
    if (running) return;
    running = true;
    clock.getDelta();
    loop();
  }
  function stop() { running = false; }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stop(); } else if (heroVisible) { start(); }
  });
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      heroVisible = entries[0].isIntersecting;
      if (heroVisible && !document.hidden) { start(); } else { stop(); }
    }, { threshold: 0.02 }).observe(canvas);
  }

  /* --- First frame + reveal ------------------------------------------------------ */
  // Unhide the canvas FIRST so layout() reads real dimensions, then fade in.
  canvas.classList.remove('hidden');
  layout();
  render();
  canvas.classList.add('is-on');
  var orb = host.querySelector('.orb-fallback');
  if (orb) {
    orb.style.transition = 'opacity .9s ease';
    orb.style.opacity = '0';
    window.setTimeout(function () { orb.style.display = 'none'; }, 950);
  }

  if (reduceMotion !== true && !document.hidden) start();
  // If the tab was hidden at load, visibilitychange restarts us.
})();
