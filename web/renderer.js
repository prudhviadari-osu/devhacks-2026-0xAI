// renderer.js — draws the Python sim in a browser canvas.
//
// Polls the state server's /state each tick (unchanged data flow) and renders
// champions, minions, structures, the objective and attack/cast effects.
// Drawing runs on requestAnimationFrame for smooth motion; the latest snapshot
// from the server is the only source of truth — the browser is a pure display.
//
// Server URL: same host, port 8765 by default. Change SERVER below if needed.

const SERVER = "http://127.0.0.1:8765";
const POLL_MS = 100;            // match the sim tick (10 Hz)

const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const mmCanvas = document.getElementById("mm");
const mctx = mmCanvas ? mmCanvas.getContext("2d") : null;
const statusEl = document.getElementById("status");
const descEl = document.getElementById("desc");
const champsPanel = document.getElementById("champs");
const feedLines = document.getElementById("feedlines");
const scenarioSel = document.getElementById("scenario");

const perfNow = () => performance.now();
let MAP = 15000;                // updated from server
let latest = null;              // most recent snapshot from the server
const drawPos = {};             // name -> smoothed draw state (world units)
const fxFlashes = [];           // recent effects, fade over time
const floaters = [];
const plates = [];               // overhead HP plates, drawn after all bodies            // floating damage / heal numbers
let banner = null;              // kill / victory banner
let lastScore = null;

const DISPLAY = '"Cinzel", "Times New Roman", serif';
const UI = '"Inter", system-ui, sans-serif';
const TEAM = {
  ALLY:  { main: "#2fa8ff", hi: "#8fd0ff", dark: "#0b3d66", rgb: "47,168,255" },
  ENEMY: { main: "#e84057", hi: "#ff9aa8", dark: "#5c1020", rgb: "232,64,87" },
};
const team = t => TEAM[t] || TEAM.ALLY;

// per-champion identity colour (token fill + particles)
const PARTICLE = {
  Ashe:   "140,210,255", Sona:   "120,230,200", Ryze:   "150,120,255",
  Jax:    "255,190,90",  Zac:    "150,230,120", Darius: "230,90,80",
  Lux:    "255,240,140", Leona:  "255,200,80",  Ahri:   "255,130,200",
  Lulu:   "200,160,255", _default: "200,200,210",
};
const particles = [];   // live particles {x,y,vx,vy,life,color}

function emitParticles(wx, wy, name, n, speed) {
  const color = PARTICLE[name] || PARTICLE._default;
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const sp = (0.3 + Math.random() * 0.7) * speed;
    particles.push({ x: wx, y: wy, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, color });
  }
}

function drawParticles(k) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let i = particles.length - 1; i >= 0; i--) {
    const pt = particles[i];
    pt.x += pt.vx * k; pt.y += pt.vy * k; pt.life -= 0.045 * k;
    if (pt.life <= 0) { particles.splice(i, 1); continue; }
    const [sx, sy] = toScreen(pt.x, pt.y);
    const r = Math.max(1, scalePx(55) * pt.life);
    ctx.fillStyle = `rgba(${pt.color},${pt.life * 0.8})`;
    ctx.beginPath(); ctx.arc(sx, sy, r, 0, 7); ctx.fill();
  }
  ctx.restore();
}
const feed = [];                // combat feed lines

// ---- canvas sizing (crisp on high-DPI phones) ----
let W = 0, H = 0, DPR = 1;
function resize() {
  DPR = Math.min(2, window.devicePixelRatio || 1);
  W = canvas.clientWidth; H = canvas.clientHeight;
  canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
  if (mmCanvas) {
    const m = mmCanvas.clientWidth;
    mmCanvas.width = Math.round(m * DPR); mmCanvas.height = Math.round(m * DPR);
  }
}
window.addEventListener("resize", resize);
resize();

// ---- dynamic camera: follows + zooms into the main action ----
const cam = { cx: 7500, cy: 7500, view: MAP, tcx: 7500, tcy: 7500, tview: MAP };
let autoCam = true;   // toggle with the button; false = whole-map overview

const CLUSTER_RADIUS = 3500;
const PADDING = 2800;
const MIN_VIEW = 4500;

function updateCamera(snap, k) {
  const champs = (snap.champions || []).filter(c => c.alive);
  if (!autoCam || champs.length === 0) {
    cam.tcx = MAP/2; cam.tcy = MAP/2; cam.tview = MAP;
  } else {
    let bestSeed = champs[0], bestCount = -1;
    for (const c of champs) {
      const cnt = champs.filter(o =>
        (o.x-c.x)**2 + (o.y-c.y)**2 < CLUSTER_RADIUS**2).length;
      if (cnt > bestCount) { bestCount = cnt; bestSeed = c; }
    }
    const group = champs.filter(o =>
      (o.x-bestSeed.x)**2 + (o.y-bestSeed.y)**2 < (CLUSTER_RADIUS*1.3)**2);
    let minx=1e9, miny=1e9, maxx=-1e9, maxy=-1e9;
    for (const c of group) {
      minx=Math.min(minx,c.x); maxx=Math.max(maxx,c.x);
      miny=Math.min(miny,c.y); maxy=Math.max(maxy,c.y);
    }
    cam.tcx = (minx+maxx)/2; cam.tcy = (miny+maxy)/2;
    const extent = Math.max(maxx-minx, maxy-miny) + PADDING * 2;
    cam.tview = Math.max(MIN_VIEW, Math.min(MAP, extent));
  }
  // frame-rate independent glide
  const a = 1 - Math.pow(1 - 0.07, k), b = 1 - Math.pow(1 - 0.05, k);
  cam.cx += (cam.tcx - cam.cx) * a;
  cam.cy += (cam.tcy - cam.cy) * a;
  cam.view += (cam.tview - cam.view) * b;
}

// world (0..MAP, y-up) -> screen (CSS pixels, y-down) through the camera
function toScreen(x, y) {
  const scale = Math.min(W, H) / cam.view;
  return [W / 2 + (x - cam.cx) * scale, H / 2 - (y - cam.cy) * scale];
}
function scalePx(units) { return units * (Math.min(W, H) / cam.view); }

// =====================================================================
//  Terrain: painted once into an offscreen texture, then blitted
// =====================================================================
const TEX = 2048;
let terrain = null, terrainMap = 0;

function rng(seed) { return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }

function buildTerrain() {
  const t = document.createElement("canvas");
  t.width = t.height = TEX;
  const g = t.getContext("2d");
  const R = rng(1337);
  const P = (x, y) => [x / MAP * TEX, (1 - y / MAP) * TEX];
  const U = u => u / MAP * TEX;

  // base: deep jungle green
  const bg = g.createRadialGradient(TEX/2, TEX/2, TEX*0.1, TEX/2, TEX/2, TEX*0.75);
  bg.addColorStop(0, "#1d3a26"); bg.addColorStop(1, "#0c1d13");
  g.fillStyle = bg; g.fillRect(0, 0, TEX, TEX);
  // mottled grass
  for (let i = 0; i < 2600; i++) {
    const x = R() * TEX, y = R() * TEX, r = 6 + R() * 40;
    const l = R();
    g.fillStyle = l < 0.5 ? `rgba(40,80,45,${0.08 + R()*0.12})` : `rgba(8,22,14,${0.1 + R()*0.15})`;
    g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
  }

  const path = (pts, w, col, blur) => {
    g.save(); g.strokeStyle = col; g.lineWidth = w; g.lineCap = "round"; g.lineJoin = "round";
    if (blur) { g.shadowColor = col; g.shadowBlur = blur; }
    g.beginPath(); pts.forEach(([x, y], i) => { const [px, py] = P(x, y); i ? g.lineTo(px, py) : g.moveTo(px, py); });
    g.stroke(); g.restore();
  };
  const LANE_TOP = [[1400, 1400], [1400, 13600], [13600, 13600]];
  const LANE_BOT = [[1400, 1400], [13600, 1400], [13600, 13600]];
  const LANE_MID = [[1400, 1400], [13600, 13600]];
  const RIVER = [[600, 14400], [4200, 10200], [7500, 7500], [10800, 4800], [14400, 600]];

  // jungle canopy (dense trees everywhere first; lanes and river carve through)
  for (let i = 0; i < 1500; i++) {
    const x = R() * TEX, y = R() * TEX, r = 10 + R() * 26;
    g.fillStyle = `rgba(6,${20 + (R()*20)|0},12,.55)`;
    g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    g.fillStyle = `rgba(60,110,60,${0.08 + R()*0.1})`;
    g.beginPath(); g.arc(x - r*0.3, y - r*0.3, r*0.55, 0, 7); g.fill();
  }

  // river: dark bed, water, shimmering highlight
  path(RIVER, U(1900), "#0b1f1d");
  path(RIVER, U(1450), "#13404f", 30);
  path(RIVER, U(900), "#1a5f74");
  path(RIVER, U(260), "rgba(120,210,230,.18)");
  // lanes: carved dirt with worn edges + paving
  for (const L of [LANE_TOP, LANE_BOT, LANE_MID]) {
    path(L, U(1750), "rgba(8,14,10,.7)");
    path(L, U(1450), "#4a4232");
    path(L, U(1150), "#5c5340");
    path(L, U(500), "rgba(140,125,95,.18)");
  }
  // pebble/noise on the lanes
  for (let i = 0; i < 4000; i++) {
    const x = R() * TEX, y = R() * TEX;
    g.fillStyle = `rgba(${R() < 0.5 ? "20,16,10" : "160,145,110"},${0.05 + R()*0.08})`;
    g.fillRect(x, y, 2 + R()*3, 2 + R()*3);
  }

  // brush patches along lanes and river
  const brush = (x, y, n) => {
    for (let i = 0; i < n; i++) {
      const [px, py] = P(x + (R()-.5)*900, y + (R()-.5)*900);
      g.fillStyle = `rgba(${30 + R()*30|0},${90 + R()*50|0},${40 + R()*20|0},.55)`;
      g.beginPath(); g.ellipse(px, py, 4 + R()*6, 2 + R()*3, R()*3, 0, 7); g.fill();
    }
  };
  [[2600, 12200], [12400, 2600], [6100, 8900], [8900, 6100], [4300, 6200], [10700, 8800],
   [6200, 4300], [8800, 10700], [3000, 9000], [12000, 6000], [9000, 3000], [6000, 12000]]
    .forEach(([x, y]) => brush(x, y, 90));

  // bases: stone plaza + team glow
  const base = (x, y, rgb) => {
    const [px, py] = P(x, y), r = U(2700);
    const gl = g.createRadialGradient(px, py, 0, px, py, r * 1.25);
    gl.addColorStop(0, `rgba(${rgb},.38)`); gl.addColorStop(0.6, `rgba(${rgb},.12)`); gl.addColorStop(1, `rgba(${rgb},0)`);
    g.fillStyle = gl; g.beginPath(); g.arc(px, py, r * 1.25, 0, 7); g.fill();
    g.fillStyle = "#3b3a36"; g.beginPath(); g.arc(px, py, r * 0.62, 0, 7); g.fill();
    g.strokeStyle = "#6e675a"; g.lineWidth = 3; g.stroke();
    for (let k = 1; k <= 3; k++) {
      g.strokeStyle = `rgba(200,170,110,${0.28 - k*0.06})`; g.lineWidth = 2;
      g.beginPath(); g.arc(px, py, r * (0.2 * k), 0, 7); g.stroke();
    }
    for (let a = 0; a < 16; a++) {   // flagstone spokes
      const ang = a / 16 * Math.PI * 2;
      g.strokeStyle = "rgba(0,0,0,.25)"; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(px + Math.cos(ang) * r*0.2, py + Math.sin(ang) * r*0.2);
      g.lineTo(px + Math.cos(ang) * r*0.62, py + Math.sin(ang) * r*0.62); g.stroke();
    }
  };
  base(1000, 1000, "47,168,255");
  base(14000, 14000, "232,64,87");

  // dragon pit
  {
    const [px, py] = P(9866, 4414), r = U(900);
    g.fillStyle = "#241a12"; g.beginPath(); g.arc(px, py, r, 0, 7); g.fill();
    g.strokeStyle = "#5a4630"; g.lineWidth = 3; g.stroke();
    g.strokeStyle = "rgba(255,140,60,.25)"; g.lineWidth = 1.5;
    g.beginPath(); g.arc(px, py, r * 0.7, 0, 7); g.stroke();
  }

  // rocks along lane edges
  for (let i = 0; i < 260; i++) {
    const x = R() * TEX, y = R() * TEX, r = 3 + R() * 7;
    g.fillStyle = `rgba(${70 + R()*30|0},${70 + R()*25|0},${65 + R()*20|0},.5)`;
    g.beginPath(); g.ellipse(x, y, r, r * 0.7, R()*3, 0, 7); g.fill();
  }

  // vignette on the map edges
  const vg = g.createRadialGradient(TEX/2, TEX/2, TEX*0.45, TEX/2, TEX/2, TEX*0.75);
  vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,.55)");
  g.fillStyle = vg; g.fillRect(0, 0, TEX, TEX);

  terrain = t; terrainMap = MAP;
}

// dense forest beyond the map edge (instead of a black void)
let voidPattern = null;
(function () {
  const t = document.createElement("canvas"); t.width = t.height = 160;
  const g = t.getContext("2d"), R = rng(77);
  g.fillStyle = "#06140c"; g.fillRect(0, 0, 160, 160);
  for (let i = 0; i < 60; i++) {
    const x = R() * 160, y = R() * 160, r = 8 + R() * 16;
    g.fillStyle = `rgba(${10 + R()*12|0},${32 + R()*22|0},${18 + R()*10|0},.8)`;
    g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    g.fillStyle = "rgba(70,120,70,.12)";
    g.beginPath(); g.arc(x - r*0.3, y - r*0.3, r*0.5, 0, 7); g.fill();
  }
  voidPattern = canvas.getContext("2d").createPattern(t, "repeat");
})();

function drawMap(now) {
  ctx.fillStyle = voidPattern || "#06140c"; ctx.fillRect(0, 0, W, H);
  if (!terrain || terrainMap !== MAP) buildTerrain();
  const [x0, y0] = toScreen(0, MAP), [x1, y1] = toScreen(MAP, 0);
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(terrain, x0, y0, x1 - x0, y1 - y0);

  // living river shimmer
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 7; i++) {
    const t = ((now / 9000) + i / 7) % 1;
    const wx = 600 + t * 13800, wy = 14400 - t * 13800;
    const [sx, sy] = toScreen(wx, wy);
    const r = scalePx(700);
    const gr = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
    gr.addColorStop(0, "rgba(90,200,230,.10)"); gr.addColorStop(1, "rgba(90,200,230,0)");
    ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(sx, sy, r, 0, 7); ctx.fill();
  }
  ctx.restore();
}

// ambient motes drifting over the battlefield (screen space)
const motes = Array.from({ length: 46 }, () => ({
  x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.6,
  s: 0.2 + Math.random() * 0.6, p: Math.random() * 6.28,
}));
function drawMotes(now, k) {
  ctx.save(); ctx.globalCompositeOperation = "lighter";
  for (const m of motes) {
    m.y -= 0.00025 * m.s * k; if (m.y < -0.02) { m.y = 1.02; m.x = Math.random(); }
    const a = 0.25 + 0.25 * Math.sin(now / 700 + m.p);
    const x = (m.x + 0.01 * Math.sin(now / 2000 + m.p)) * W, y = m.y * H;
    ctx.fillStyle = `rgba(200,240,170,${a})`;
    ctx.beginPath(); ctx.arc(x, y, m.r, 0, 7); ctx.fill();
  }
  ctx.restore();
}

// =====================================================================
//  Entities
// =====================================================================
function drawObjective(o, now) {
  const [x, y] = toScreen(o.x, o.y);
  const r = Math.max(10, scalePx(420));
  ctx.save();
  if (o.up) {
    const pulse = 1 + 0.08 * Math.sin(now / 250);
    const gl = ctx.createRadialGradient(x, y, 0, x, y, r * 2.6 * pulse);
    gl.addColorStop(0, "rgba(255,150,60,.55)"); gl.addColorStop(1, "rgba(255,90,30,0)");
    ctx.fillStyle = gl; ctx.beginPath(); ctx.arc(x, y, r * 2.6 * pulse, 0, 7); ctx.fill();
    // rotating rune ring
    ctx.translate(x, y); ctx.rotate(now / 2400);
    ctx.strokeStyle = "rgba(255,190,110,.75)"; ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 6]); ctx.beginPath(); ctx.arc(0, 0, r * 1.5, 0, 7); ctx.stroke();
    ctx.setLineDash([]); ctx.rotate(-now / 2400);
    // stylised drake sigil: wings + body
    ctx.fillStyle = "#ffb15a"; ctx.shadowColor = "#ff7a2a"; ctx.shadowBlur = 18;
    ctx.beginPath();
    ctx.moveTo(0, -r); ctx.quadraticCurveTo(r * 0.5, -r * 0.2, r * 1.3, -r * 0.5);
    ctx.quadraticCurveTo(r * 0.8, r * 0.1, r * 0.35, r * 0.25);
    ctx.lineTo(0, r * 1.05); ctx.lineTo(-r * 0.35, r * 0.25);
    ctx.quadraticCurveTo(-r * 0.8, r * 0.1, -r * 1.3, -r * 0.5);
    ctx.quadraticCurveTo(-r * 0.5, -r * 0.2, 0, -r);
    ctx.fill();
    ctx.shadowBlur = 0; ctx.fillStyle = "#fff3d6";
    ctx.beginPath(); ctx.arc(0, -r * 0.2, r * 0.18, 0, 7); ctx.fill();
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  } else {
    ctx.strokeStyle = "rgba(160,155,140,.5)"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
    // respawn progress arc (visual countdown, assumes a 5-minute timer cap)
    const frac = Math.max(0, Math.min(1, 1 - (o.spawns_in || 0) / 300));
    ctx.strokeStyle = "#c8aa6e"; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + frac * Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
  label(o.up ? "DRAGON" : `DRAGON  ${o.spawns_in | 0}s`, x, y + r + 16,
        o.up ? "#ffcf8a" : "#a09b8c", 11, DISPLAY, 700);
}

function label(text, x, y, color, size, font, weight) {
  ctx.save();
  ctx.font = `${weight || 600} ${size}px ${font || UI}`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,.85)"; ctx.lineJoin = "round";
  ctx.strokeText(text, x, y);
  ctx.fillStyle = color; ctx.fillText(text, x, y);
  ctx.restore();
}

function drawStructure(s, now) {
  let [x, y] = toScreen(s.x, s.y);
  const isNexus = s.kind === "nexus";
  if (isNexus && cam.view > MAP * 0.9) { x = Math.max(34, Math.min(W - 34, x)); y = Math.max(34, Math.min(H - 34, y)); }
  const T = team(s.team);
  const u = isNexus ? Math.max(16, scalePx(420)) : Math.max(7, scalePx(230));

  // ground shadow / plinth
  ctx.fillStyle = "rgba(0,0,0,.45)";
  ctx.beginPath(); ctx.ellipse(x, y + u * 0.55, u * 1.05, u * 0.42, 0, 0, 7); ctx.fill();

  if (!s.alive) {   // rubble
    ctx.fillStyle = "#3a3832";
    for (let i = 0; i < 5; i++) {
      const a = i * 1.3, d = u * 0.45;
      ctx.beginPath(); ctx.arc(x + Math.cos(a) * d, y + u * 0.35 + Math.sin(a) * d * 0.4, u * 0.28, 0, 7); ctx.fill();
    }
    ctx.strokeStyle = "rgba(160,155,140,.45)"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(x - u*0.5, y); ctx.lineTo(x + u*0.5, y + u*0.6); ctx.stroke();
    return;
  }

  // stone base
  const sb = ctx.createLinearGradient(x, y, x, y + u * 0.8);
  sb.addColorStop(0, "#6e675a"); sb.addColorStop(1, "#2c2a25");
  ctx.fillStyle = sb;
  ctx.beginPath(); ctx.ellipse(x, y + u * 0.45, u * 0.85, u * 0.36, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = "#c8aa6e"; ctx.lineWidth = 1; ctx.stroke();

  // crystal
  const bob = Math.sin(now / 600 + s.x) * u * 0.06;
  const top = y - u * (isNexus ? 1.6 : 1.9) + bob, mid = y - u * 0.35 + bob, bot = y + u * 0.35 + bob;
  const wdt = u * (isNexus ? 0.95 : 0.55);
  ctx.save();
  ctx.shadowColor = T.main; ctx.shadowBlur = isNexus ? 30 : 16;
  const cg = ctx.createLinearGradient(x - wdt, top, x + wdt, bot);
  cg.addColorStop(0, T.hi); cg.addColorStop(0.5, T.main); cg.addColorStop(1, T.dark);
  ctx.fillStyle = cg;
  ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x + wdt, mid); ctx.lineTo(x, bot); ctx.lineTo(x - wdt, mid); ctx.closePath();
  ctx.fill();
  ctx.restore();
  ctx.fillStyle = "rgba(255,255,255,.35)";      // facet
  ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x - wdt, mid); ctx.lineTo(x, mid + (bot - mid) * 0.2); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = "rgba(240,230,210,.8)"; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x + wdt, mid); ctx.lineTo(x, bot); ctx.lineTo(x - wdt, mid); ctx.closePath(); ctx.stroke();

  if (isNexus) {   // orbiting rings
    ctx.save(); ctx.translate(x, mid);
    for (let i = 0; i < 2; i++) {
      ctx.rotate(now / (1400 + i * 600) * (i ? -1 : 1));
      ctx.strokeStyle = `rgba(${T.rgb},${0.55 - i * 0.2})`; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.ellipse(0, 0, u * (1.5 + i * 0.4), u * (0.45 + i * 0.12), 0, 0, 7); ctx.stroke();
    }
    ctx.restore();
  }

  // health bar
  const bw = Math.max(28, u * (isNexus ? 2.6 : 2.4)), bh = isNexus ? 6 : 4;
  const by = top - (isNexus ? 14 : 9);
  ctx.fillStyle = "#010a13"; ctx.fillRect(x - bw/2 - 1, by - 1, bw + 2, bh + 2);
  ctx.fillStyle = T.main; ctx.fillRect(x - bw/2, by, bw * s.hp_frac, bh);
  ctx.strokeStyle = "#785a28"; ctx.lineWidth = 1; ctx.strokeRect(x - bw/2 - 1.5, by - 1.5, bw + 3, bh + 3);
  if (isNexus) label("NEXUS", x, bot + u * 0.75, T.hi, 11, DISPLAY, 700);
}

function drawMinion(m) {
  const [x, y] = toScreen(m.x, m.y);
  const T = team(m.team);
  const s = Math.max(2.2, scalePx(m.kind === "siege" ? 95 : 65));
  ctx.fillStyle = "rgba(0,0,0,.4)";
  ctx.beginPath(); ctx.ellipse(x, y + s * 0.9, s, s * 0.4, 0, 0, 7); ctx.fill();
  ctx.fillStyle = T.main; ctx.strokeStyle = "rgba(0,0,0,.8)"; ctx.lineWidth = 1;
  ctx.beginPath();
  if (m.kind === "siege") ctx.rect(x - s, y - s, s * 2, s * 2);
  else { ctx.moveTo(x, y - s * 1.2); ctx.lineTo(x + s, y); ctx.lineTo(x, y + s * 1.2); ctx.lineTo(x - s, y); ctx.closePath(); }
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = "rgba(255,255,255,.35)";
  ctx.fillRect(x - s * 0.3, y - s * 0.5, s * 0.4, s * 0.4);
  if (s > 4 && m.hp_frac != null && m.hp_frac < 1) {
    const bw = s * 2.6;
    ctx.fillStyle = "#000"; ctx.fillRect(x - bw/2, y - s * 1.2 - 5, bw, 3);
    ctx.fillStyle = T.main; ctx.fillRect(x - bw/2, y - s * 1.2 - 5, bw * m.hp_frac, 3);
  }
}

// =====================================================================
//  Attack VFX: world-space particle system (additive blending)
// =====================================================================
const pfx = [];                 // {x,y,vx,vy,life,decay,size,col,kind,ang,spin,grav}
const pxToWorld = px => px * cam.view / Math.min(W, H);
const MAX_PFX = 1400;

function spawn(o) {
  if (pfx.length > MAX_PFX) pfx.splice(0, pfx.length - MAX_PFX);
  pfx.push(Object.assign({ vx: 0, vy: 0, life: 1, decay: 0.05, size: 3, kind: "dot",
                           ang: 0, spin: 0, grav: 0 }, o));
}
// n particles bursting from world point (wx,wy); speed in px/frame
function burst(wx, wy, n, col, speed, o = {}) {
  for (let i = 0; i < n; i++) {
    const a = (o.dir != null ? o.dir + (Math.random() - 0.5) * (o.spread || 1.2) : Math.random() * 6.283);
    const sp = pxToWorld(speed * (0.35 + Math.random() * 0.65));
    spawn({ x: wx, y: wy, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, col,
            kind: o.kind || "spark", size: (o.size || 3) * (0.6 + Math.random() * 0.8),
            decay: (o.decay || 0.05) * (0.7 + Math.random() * 0.6), grav: o.grav || 0 });
  }
}

function fxColor(e) {
  if (e.kind === "heal") return "110,240,160";
  if (e.kind === "cast" && e.cc) return "255,215,90";
  return e.col || (e.kind === "cast" ? "190,120,255" : "255,236,190");
}

// called once when the server reports a new effect
function startFx(e) {
  const col = fxColor(e);
  const dir = Math.atan2(e.dst_y - e.src_y, e.dst_x - e.src_x);
  if (e.kind === "cast") {
    spawn({ x: e.src_x, y: e.src_y, kind: "circle", size: 30, col, decay: 0.03, spin: 0.08 });
    burst(e.src_x, e.src_y, 10, col, 3, { kind: "dot", size: 3.5, decay: 0.04 });
  } else if (e.kind === "heal") {
    spawn({ x: e.src_x, y: e.src_y, kind: "circle", size: 22, col, decay: 0.035, spin: -0.06 });
  } else if (!e.melee) {
    burst(e.src_x, e.src_y, 6, col, 3.5, { dir, spread: 0.9, size: 3, decay: 0.08 });   // muzzle flash
    spawn({ x: e.src_x, y: e.src_y, kind: "flash", size: 12, col, decay: 0.15 });
  }
}

// called once when the projectile reaches its target
function impactFx(e) {
  const col = fxColor(e), x = e.dst_x, y = e.dst_y;
  const dir = Math.atan2(e.dst_y - e.src_y, e.dst_x - e.src_x);
  if (e.kind === "heal") {
    for (let i = 0; i < 12; i++)
      spawn({ x: x + pxToWorld((Math.random() - .5) * 34), y: y + pxToWorld(Math.random() * 20),
              vy: pxToWorld(0.9 + Math.random() * 0.8), kind: "plus", size: 3 + Math.random() * 3,
              col, decay: 0.022 + Math.random() * 0.015 });
    spawn({ x, y, kind: "ring", size: 8, col, decay: 0.04 });
    return;
  }
  if (e.melee) {
    spawn({ x, y, kind: "slash", size: 22, col, decay: 0.07, ang: -dir + (Math.random() - .5) * 0.8 });
    burst(x, y, 9, col, 5, { dir, spread: 1.6, size: 3, decay: 0.07 });
    spawn({ x, y, kind: "flash", size: 16, col: "255,255,255", decay: 0.14 });
    return;
  }
  const big = e.kind === "cast";
  spawn({ x, y, kind: "flash", size: big ? 30 : 16, col: big ? col : "255,255,255", decay: big ? 0.08 : 0.14 });
  spawn({ x, y, kind: "ring", size: big ? 10 : 5, col, decay: big ? 0.035 : 0.06 });
  if (big) spawn({ x, y, kind: "ring", size: 4, col: "255,255,255", decay: 0.05 });
  burst(x, y, big ? 22 : 9, col, big ? 6 : 4, { size: big ? 3.5 : 2.6, decay: big ? 0.04 : 0.065, grav: big ? 0 : -0.04 });
  burst(x, y, big ? 10 : 4, "255,255,255", big ? 3 : 2, { kind: "dot", size: 2, decay: 0.06 });
  if (e.cc) for (let i = 0; i < 6; i++)
    spawn({ x, y, kind: "star", size: 5, col: "255,215,90", decay: 0.035,
            vx: pxToWorld(Math.cos(i * 1.05) * 2.2), vy: pxToWorld(Math.sin(i * 1.05) * 2.2), spin: 0.15 });
}

function drawFx(k) {
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.lineCap = "round";
  for (let i = fxFlashes.length - 1; i >= 0; i--) {
    const e = fxFlashes[i];
    if (!e.started) { e.started = true; startFx(e); }
    const col = fxColor(e);
    const [ax, ay] = toScreen(e.src_x, e.src_y), [bx, by] = toScreen(e.dst_x, e.dst_y);
    const cast = e.kind === "cast" || e.kind === "heal";
    const t = Math.min(1, e.age);
    if (!e.melee && t < 1) {
      const px = ax + (bx - ax) * t, py = ay + (by - ay) * t;
      const wx = e.src_x + (e.dst_x - e.src_x) * t, wy = e.src_y + (e.dst_y - e.src_y) * t;
      // comet tail
      const tt = Math.max(0, t - 0.35);
      const tx = ax + (bx - ax) * tt, ty = ay + (by - ay) * tt;
      const tg = ctx.createLinearGradient(tx, ty, px, py);
      tg.addColorStop(0, `rgba(${col},0)`); tg.addColorStop(1, `rgba(${col},.9)`);
      ctx.strokeStyle = tg; ctx.lineWidth = cast ? 7 : 3.5;
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(px, py); ctx.stroke();
      // glowing head
      const hr = cast ? 11 : 6;
      const hg = ctx.createRadialGradient(px, py, 0, px, py, hr * 2);
      hg.addColorStop(0, "rgba(255,255,255,1)"); hg.addColorStop(0.3, `rgba(${col},1)`); hg.addColorStop(1, `rgba(${col},0)`);
      ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(px, py, hr * 2, 0, 7); ctx.fill();
      // sparkle trail
      const n = cast ? 3 : 1;
      for (let j = 0; j < n; j++) if (Math.random() < 0.9 * k)
        spawn({ x: wx, y: wy, vx: pxToWorld((Math.random() - .5) * 1.2), vy: pxToWorld((Math.random() - .5) * 1.2),
                kind: cast && Math.random() < 0.3 ? "star" : "dot", size: cast ? 3.5 : 2.4, col, decay: 0.06, spin: 0.1 });
    }
    if (t >= 1 && !e.hit) { e.hit = true; impactFx(e); }
    e.age += (e.melee ? 0.5 : cast ? 0.13 : 0.18) * k;
    e.life -= 0.045 * k;
    if (e.life <= 0 && e.hit) fxFlashes.splice(i, 1);
  }

  // particles
  const now = perfNow();
  for (let i = pfx.length - 1; i >= 0; i--) {
    const q = pfx[i];
    q.x += q.vx * k; q.y += q.vy * k; q.vx *= Math.pow(0.93, k); q.vy *= Math.pow(0.93, k);
    q.vy += pxToWorld(q.grav) * k; q.ang += q.spin * k; q.life -= q.decay * k;
    if (q.life <= 0) { pfx.splice(i, 1); continue; }
    const [x, y] = toScreen(q.x, q.y), L = q.life, c = q.col;
    switch (q.kind) {
      case "dot": {
        const r = q.size * (0.5 + L);
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * 2);
        g.addColorStop(0, `rgba(255,255,255,${L})`); g.addColorStop(0.35, `rgba(${c},${L})`); g.addColorStop(1, `rgba(${c},0)`);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 2, 0, 7); ctx.fill();
        break;
      }
      case "spark": {
        const s = Math.min(W, H) / cam.view, vx = q.vx * s, vy = -q.vy * s;
        ctx.strokeStyle = `rgba(${c},${L})`; ctx.lineWidth = q.size * 0.6 * (0.4 + L);
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - vx * 3, y - vy * 3); ctx.stroke();
        ctx.fillStyle = `rgba(255,255,255,${L})`; ctx.fillRect(x - 1, y - 1, 2, 2);
        break;
      }
      case "ring": {
        const r = q.size + (1 - L) * 38;
        ctx.strokeStyle = `rgba(${c},${L})`; ctx.lineWidth = 3 * L + 0.5;
        ctx.beginPath(); ctx.ellipse(x, y, r, r * 0.55, 0, 0, 7); ctx.stroke();
        break;
      }
      case "flash": {
        const r = q.size * (1.4 - L * 0.4);
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(255,255,255,${L})`); g.addColorStop(0.4, `rgba(${c},${L * 0.7})`); g.addColorStop(1, `rgba(${c},0)`);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
        break;
      }
      case "circle": {   // rotating magic circle on the ground under the caster
        const grow = Math.min(1, (1 - L) * 5), r = q.size * grow;
        ctx.save(); ctx.translate(x, y); ctx.scale(1, 0.5); ctx.rotate(q.ang);
        ctx.strokeStyle = `rgba(${c},${L})`; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(0, 0, r, 0, 7); ctx.stroke();
        ctx.beginPath(); ctx.arc(0, 0, r * 0.72, 0, 7); ctx.stroke();
        ctx.lineWidth = 1.5; ctx.beginPath();
        for (let j = 0; j < 6; j++) {             // hexagram
          const a1 = j * Math.PI / 3, a2 = a1 + Math.PI * 2 / 3;
          ctx.moveTo(Math.cos(a1) * r * 0.72, Math.sin(a1) * r * 0.72);
          ctx.lineTo(Math.cos(a2) * r * 0.72, Math.sin(a2) * r * 0.72);
        }
        ctx.stroke();
        ctx.fillStyle = `rgba(${c},${L})`;
        for (let j = 0; j < 12; j++) {
          const a = j * Math.PI / 6;
          ctx.fillRect(Math.cos(a) * r * 0.86 - 1.5, Math.sin(a) * r * 0.86 - 1.5, 3, 3);
        }
        ctx.restore();
        break;
      }
      case "slash": {    // crescent swipe for melee hits
        const r = q.size * (1.1 - L * 0.2), sweep = 2.4 * Math.min(1, (1 - L) * 4 + 0.3);
        ctx.save(); ctx.translate(x, y); ctx.rotate(q.ang - sweep / 2 + Math.PI / 2);
        for (let j = 0; j < 3; j++) {
          ctx.strokeStyle = j === 0 ? `rgba(255,255,255,${L})` : `rgba(${c},${L * (0.8 - j * 0.25)})`;
          ctx.lineWidth = (7 - j * 2) * L + 1;
          ctx.beginPath(); ctx.arc(0, 0, r - j * 4, 0, sweep); ctx.stroke();
        }
        ctx.restore();
        break;
      }
      case "plus": {
        const s = q.size * (0.6 + L * 0.4);
        ctx.fillStyle = `rgba(${c},${L})`;
        ctx.fillRect(x - s, y - s * 0.3, s * 2, s * 0.6); ctx.fillRect(x - s * 0.3, y - s, s * 0.6, s * 2);
        break;
      }
      case "star": {
        const s = q.size * (0.6 + L * 0.6);
        ctx.save(); ctx.translate(x, y); ctx.rotate(q.ang);
        ctx.fillStyle = `rgba(${c},${L})`; ctx.beginPath();
        for (let j = 0; j < 8; j++) {
          const a = j * Math.PI / 4, rr = j % 2 ? s * 0.3 : s;
          ctx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr);
        }
        ctx.closePath(); ctx.fill(); ctx.restore();
        break;
      }
    }
  }
  ctx.restore();
}

function drawChampion(c, p, now, k) {
  const [x, y] = toScreen(p.x, p.y);
  const T = team(c.team);
  const idc = PARTICLE[c.name] || PARTICLE._default;
  const moving = Math.hypot(p.sx, p.sy) > 0.6;
  ctx.globalAlpha = p.spawnFade;

  // attack-range ring: only while this champion is attacking (less clutter)
  if (p.atk > 0.05) {
    ctx.save();
    ctx.strokeStyle = `rgba(${T.rgb},${0.18 * p.atk})`; ctx.lineWidth = 1; ctx.setLineDash([3, 6]);
    ctx.beginPath(); ctx.ellipse(x, y, scalePx(c.attack_range || 550), scalePx(c.attack_range || 550) * 0.9, 0, 0, 7); ctx.stroke();
    ctx.restore();
  }

  if (c.attacking) p.atk = Math.min(1, p.atk + 0.5 * (c.attack_speed || 0.7) * k);
  else p.atk = Math.max(0, p.atk - 0.15 * k);
  if (moving && Math.random() < 0.35 * k) emitParticles(p.x, p.y, c.name, 1, 12);
  if (c.attacking && Math.random() < 0.4 * k) emitParticles(p.x, p.y, c.name, 3, 22);

  // figure size tracks camera zoom (true-to-scale), clamped for legibility
  const Hc = Math.max(40, Math.min(84, scalePx(720)));
  const r = Hc * 0.32;                 // used by CC ring + plate spacing
  const yb = y - Hc * 0.48;            // visual centre of the body

  // ground: shadow + team selection circle under the feet
  ctx.fillStyle = "rgba(0,0,0,.5)";
  ctx.beginPath(); ctx.ellipse(x, y, Hc * 0.36, Hc * 0.12, 0, 0, 7); ctx.fill();
  ctx.save();
  ctx.strokeStyle = T.main; ctx.lineWidth = 2; ctx.shadowColor = T.main; ctx.shadowBlur = 10;
  ctx.globalAlpha *= 0.9;
  ctx.beginPath(); ctx.ellipse(x, y, Hc * 0.46, Hc * 0.17, 0, 0, 7); ctx.stroke();
  ctx.restore();

  // facing: toward the current attack target, else the walking direction
  if (p.face == null) p.face = c.team === "ALLY" ? 1 : -1;
  if (c.attacking && p.aimX != null && Math.abs(p.aimX) > 1) p.face = Math.sign(p.aimX);
  else if (moving && Math.abs(p.sx) > 0.3) p.face = Math.sign(p.sx);
  if (moving) p.walk = (p.walk || 0) + 0.42 * k * ((c.move_speed || 330) / 330);

  drawCharacter(ctx, c.name, x, y, Hc, {
    face: p.face, walk: p.walk || 0, moving, atk: p.atk, now,
    team: T.main, hit: p.hitFlash,
  });

  // crowd-control: spinning stars
  if (c.cc > 0) {
    ctx.save();
    for (let i = 0; i < 3; i++) {
      const a = now / 220 + i * 2.09;
      const sx = x + Math.cos(a) * r * 1.1, sy = y - Hc * 0.95 + Math.sin(a) * r * 0.3;
      ctx.fillStyle = "#ffd75a"; ctx.shadowColor = "#ffd75a"; ctx.shadowBlur = 8;
      ctx.beginPath(); ctx.arc(sx, sy, 2.4, 0, 7); ctx.fill();
    }
    ctx.strokeStyle = "rgba(255,215,90,.8)"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, yb, r + 5 + 2 * Math.sin(now / 80), 0, 7); ctx.stroke();
    ctx.restore();
  }

  ctx.globalAlpha = 1;
  const fade = p.spawnFade;
  const bw = Math.max(60, Math.min(84, Hc * 1.05));
  const headY = y - Hc * (window.characterHeight ? characterHeight(c.name) / 24 : 1);
  const y0 = headY - 16;                       // natural bar position (just above head)
  plates.push({ x, y: y0, y0, w: bw + 14, headY, draw: (by) => {
    ctx.globalAlpha = fade;
    const bh = 6, mh = 2.5, inner = bw - 10;
    const bx = x - bw / 2 + 10;
    ctx.fillStyle = "rgba(1,10,19,.92)";
    ctx.fillRect(bx - 1, by - 1, inner + 2, bh + mh + 3);
    ctx.strokeStyle = "#463714"; ctx.lineWidth = 1;
    ctx.strokeRect(bx - 1.5, by - 1.5, inner + 3, bh + mh + 4);
    p.ghost = Math.max(c.hp_frac, (p.ghost ?? c.hp_frac) - 0.01 * k);   // recent-damage ghost
    ctx.fillStyle = "#c8aa6e"; ctx.fillRect(bx, by, inner * p.ghost, bh);
    const hg = ctx.createLinearGradient(0, by, 0, by + bh);
    hg.addColorStop(0, T.hi); hg.addColorStop(1, T.main);
    ctx.fillStyle = hg; ctx.fillRect(bx, by, inner * c.hp_frac, bh);
    const segs = Math.min(40, Math.floor((c.max_hp || 1000) / 100));   // 100-hp ticks
    ctx.fillStyle = "rgba(0,0,0,.55)";
    for (let i = 1; i < segs; i++) ctx.fillRect(bx + inner * i / segs, by, 1, i % 10 === 0 ? bh : bh * 0.55);
    ctx.fillStyle = "#3a8fe8"; ctx.fillRect(bx, by + bh + 1, inner * (c.mp_frac ?? 0), mh);
    // level badge
    ctx.fillStyle = "#010a13"; ctx.strokeStyle = "#c8aa6e"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(bx - 6, by + (bh + mh) / 2, 7, 0, 7); ctx.fill(); ctx.stroke();
    ctx.font = `700 8.5px ${UI}`; ctx.fillStyle = "#f0e6d2"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(c.level, bx - 6, by + (bh + mh) / 2 + 0.5);
    label(c.name, bx + inner / 2, by - 7, c.team === "ALLY" ? "#f0e6d2" : "#ffd6dc", 10.5, DISPLAY, 700);
    ctx.globalAlpha = 1;
  } });
}

// spread overlapping HP plates apart, then draw them (with a leader line when moved)
const PLATE_H = 24;
function drawPlates() {
  const list = plates.slice().sort((a, b) => b.y0 - a.y0);   // bottom-most first
  const placed = [];
  for (const pl of list) {
    let y = pl.y0, moved = true, guard = 0;
    while (moved && guard++ < 20) {
      moved = false;
      for (const o of placed) {
        if (Math.abs(o.x - pl.x) < (o.w + pl.w) / 2 && Math.abs(o.y - y) < PLATE_H) {
          y = o.y - PLATE_H; moved = true;
        }
      }
    }
    pl.y = y; placed.push(pl);
  }
  for (const pl of placed) {
    if (pl.y0 - pl.y > 4) {
      ctx.strokeStyle = "rgba(200,170,110,.55)"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(pl.x, pl.y + 10); ctx.lineTo(pl.x, pl.headY - 2); ctx.stroke();
      ctx.fillStyle = "#c8aa6e"; ctx.beginPath(); ctx.arc(pl.x, pl.headY - 2, 1.6, 0, 7); ctx.fill();
    }
  }
  for (const pl of placed) pl.draw(pl.y);
  plates.length = 0;
}

// new numbers start above any still-fresh number on the same champion
function stackDy(name) {
  let top = -1e9;
  for (const f of floaters) if (f.who === name && f.life > 0.55) top = Math.max(top, f.dy);
  return top > -1e9 ? top + 15 : 0;
}

function drawFloaters(k) {
  for (let i = floaters.length - 1; i >= 0; i--) {
    const f = floaters[i];
    f.life -= 0.022 * k; f.dy += 0.6 * k;
    if (f.life <= 0) { floaters.splice(i, 1); continue; }
    const [x, y] = toScreen(f.x, f.y);
    ctx.save();
    ctx.globalAlpha = Math.min(1, f.life * 1.6);
    const s = 1 + 0.4 * Math.max(0, f.life - 0.8) * 5;
    label(f.text, x + f.ox, y - 30 - f.dy, f.color, Math.round((f.big ? 15 : 12) * s), UI, 800);
    ctx.restore();
  }
}

function drawDead(c) {
  if (drawPos[c.name]) drawPos[c.name].spawnFade = 0;
  const [x, y] = toScreen(c.spawn_x, c.spawn_y);
  const idx = (latest.champions || []).filter(o => !o.alive && o.team === c.team).indexOf(c);
  const yy = y - 26 - idx * 15;
  label(`☠ ${c.name}  ${c.dead_timer | 0}s`, x, yy, "#a09b8c", 10, UI, 700);
}

function drawBanner(now) {
  if (!banner) return;
  const t = (now - banner.t0) / 2200;
  if (t >= 1) { banner = null; return; }
  const a = t < 0.12 ? t / 0.12 : t > 0.8 ? (1 - t) / 0.2 : 1;
  const cy = H * 0.22, w = Math.min(W - 32, 460), h = 46;
  ctx.save();
  ctx.globalAlpha = a;
  const g = ctx.createLinearGradient(W/2 - w/2, 0, W/2 + w/2, 0);
  g.addColorStop(0, "rgba(1,10,19,0)"); g.addColorStop(0.2, "rgba(1,10,19,.88)");
  g.addColorStop(0.8, "rgba(1,10,19,.88)"); g.addColorStop(1, "rgba(1,10,19,0)");
  ctx.fillStyle = g; ctx.fillRect(W/2 - w/2, cy - h/2, w, h);
  const lg = ctx.createLinearGradient(W/2 - w/2, 0, W/2 + w/2, 0);
  lg.addColorStop(0, "rgba(200,170,110,0)"); lg.addColorStop(0.5, banner.color); lg.addColorStop(1, "rgba(200,170,110,0)");
  ctx.fillStyle = lg; ctx.fillRect(W/2 - w/2, cy - h/2, w, 1); ctx.fillRect(W/2 - w/2, cy + h/2 - 1, w, 1);
  const sc = 1 + Math.max(0, 0.12 - t) * 2;
  ctx.translate(W/2, cy); ctx.scale(sc, sc);
  ctx.font = `900 ${banner.big ? 24 : 19}px ${DISPLAY}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.shadowColor = banner.color; ctx.shadowBlur = 18; ctx.fillStyle = "#f0e6d2";
  ctx.fillText(banner.text, 0, 1);
  ctx.restore();
}

function drawMinimap(snap) {
  if (!mctx || !terrain) return;
  const S = mmCanvas.width;
  mctx.setTransform(1, 0, 0, 1, 0, 0);
  mctx.drawImage(terrain, 0, 0, S, S);
  const P = (x, y) => [x / MAP * S, (1 - y / MAP) * S];
  for (const s of snap.structures || []) {
    if (!s.alive) continue;
    const [x, y] = P(s.x, s.y), r = (s.kind === "nexus" ? 5 : 2.6) * DPR;
    mctx.fillStyle = team(s.team).main; mctx.strokeStyle = "#000"; mctx.lineWidth = DPR;
    mctx.fillRect(x - r, y - r, r * 2, r * 2); mctx.strokeRect(x - r, y - r, r * 2, r * 2);
  }
  if (snap.objective && snap.objective.up) {
    const [x, y] = P(snap.objective.x, snap.objective.y);
    mctx.fillStyle = "#ffb15a"; mctx.beginPath(); mctx.arc(x, y, 3.5 * DPR, 0, 7); mctx.fill();
  }
  for (const c of snap.champions || []) {
    if (!c.alive) continue;
    const p = drawPos[c.name] || c;
    const [x, y] = P(p.x, p.y);
    mctx.fillStyle = `rgb(${PARTICLE[c.name] || PARTICLE._default})`;
    mctx.strokeStyle = team(c.team).main; mctx.lineWidth = 2 * DPR;
    mctx.beginPath(); mctx.arc(x, y, 4.2 * DPR, 0, 7); mctx.fill(); mctx.stroke();
  }
  // camera viewport
  const sc = Math.min(W, H) / cam.view;
  const vw = W / sc, vh = H / sc;
  const [rx, ry] = P(cam.cx - vw / 2, cam.cy + vh / 2);
  mctx.strokeStyle = "rgba(240,230,210,.85)"; mctx.lineWidth = DPR;
  mctx.strokeRect(rx, ry, vw / MAP * S, vh / MAP * S);
}

// =====================================================================
//  Frame loop (visual) + snapshot ingestion (data)
// =====================================================================
let lastFrame = perfNow();
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000); lastFrame = now;
  const k = dt * 30;                 // 1.0 == one 30fps step (keeps original tuning)
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  if (!latest) {
    ctx.fillStyle = "#030907"; ctx.fillRect(0, 0, W, H);
    label("AWAITING SIMULATION", W / 2, H / 2, "#c8aa6e", 14, DISPLAY, 700);
    requestAnimationFrame(frame); return;
  }
  const snap = latest;
  MAP = snap.map_size || MAP;
  updateCamera(snap, k);
  drawMap(now);

  for (const s of snap.structures || []) drawStructure(s, now);
  drawObjective(snap.objective, now);
  for (const m of snap.minions || []) drawMinion(m);
  drawParticles(k);
  drawFx(k);

  // champions — move toward the server position at each champ's OWN speed
  const alive = [];
  for (const c of snap.champions || []) {
    if (!c.alive) continue;
    const p = drawPos[c.name] || { x: c.x, y: c.y, sx: 0, sy: 0, hp: c.hp_frac,
                                   hitFlash: 0, spawnFade: 0, atk: 0 };
    const dx = c.x - p.x, dy = c.y - p.y;
    const dist = Math.hypot(dx, dy);
    if (dist > 2500) { p.x = c.x; p.y = c.y; }          // respawn / teleport: snap
    else {
      const speed = (c.move_speed || 330) * dt * 1.15;
      const stepLen = Math.min(speed, dist);
      const ox = p.x, oy = p.y;
      if (dist > 1e-3) { p.x += (dx / dist) * stepLen; p.y += (dy / dist) * stepLen; }
      p.sx = (p.x - ox) / Math.max(k, 0.01); p.sy = (p.y - oy) / Math.max(k, 0.01);
    }
    p.hitFlash = Math.max(0, p.hitFlash - 0.12 * k);
    p.spawnFade = Math.min(1, p.spawnFade + 0.08 * k);
    drawPos[c.name] = p;
    alive.push([c, p]);
  }
  alive.sort((a, b) => b[1].y - a[1].y);            // draw north-to-south for depth
  for (const [c, p] of alive) drawChampion(c, p, now, k);
  drawPlates();
  ctx.globalAlpha = 1;
  for (const c of snap.champions || []) if (!c.alive) drawDead(c);

  drawFloaters(k);
  drawMotes(now, k);
  drawBanner(now);
  drawMinimap(snap);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// called once per server snapshot: effects, damage numbers, HUD panels
function render(snap) {
  latest = snap;
  MAP = snap.map_size || MAP;
  descEl.textContent = snap.desc || "";
  for (const e of snap.fx || []) {          // face attackers toward their target
    let best = null, bd = 250 * 250;
    for (const c of snap.champions || []) {
      const d = (c.x - e.src_x) ** 2 + (c.y - e.src_y) ** 2;
      if (d < bd) { bd = d; best = c; }
    }
    if (best && drawPos[best.name]) drawPos[best.name].aimX = e.dst_x - e.src_x;
    const dist = Math.hypot(e.dst_x - e.src_x, e.dst_y - e.src_y);
    fxFlashes.push({ ...e, life: 1, age: 0,
      col: best ? (PARTICLE[best.name] || PARTICLE._default) : null,
      melee: e.kind === "auto" && dist < 320 });
  }

  for (const c of snap.champions || []) {
    const p = drawPos[c.name];
    if (!p || !c.alive) { if (p) p.hp = c.hp_frac; continue; }
    const delta = (c.hp_frac - p.hp) * (c.max_hp || 0);
    if (c.hp_frac < p.hp - 0.001) {
      p.hitFlash = 1;
      if (delta <= -1) floaters.push({ x: p.x, y: p.y, text: `${Math.round(-delta)}`, dy: stackDy(c.name), who: c.name,
        ox: (Math.random() - .5) * 16, life: 1, big: -delta > 150,
        color: c.team === "ALLY" ? "#ff8a8a" : "#ffd27a" });
    } else if (delta >= 8) {
      floaters.push({ x: p.x, y: p.y, text: `+${Math.round(delta)}`, dy: stackDy(c.name), who: c.name,
        ox: (Math.random() - .5) * 16, life: 1, color: "#7fe7a0" });
    }
    p.hp = c.hp_frac;
  }

  // kill / victory banners (derived from the score the server already sends)
  const sc = snap.score;
  if (sc && lastScore) {
    if (sc.ALLY.kills > lastScore.ALLY.kills) banner = { text: "AN ENEMY HAS BEEN SLAIN", color: "#2fa8ff", t0: perfNow() };
    else if (sc.ENEMY.kills > lastScore.ENEMY.kills) banner = { text: "AN ALLY HAS BEEN SLAIN", color: "#e84057", t0: perfNow() };
    if ((sc.ALLY.dragons || 0) > (lastScore.ALLY.dragons || 0)) banner = { text: "YOUR TEAM HAS SLAIN THE DRAGON", color: "#ffb15a", t0: perfNow() };
    else if ((sc.ENEMY.dragons || 0) > (lastScore.ENEMY.dragons || 0)) banner = { text: "ENEMY TEAM HAS SLAIN THE DRAGON", color: "#ffb15a", t0: perfNow() };
  }
  if (snap.winner && (!banner || !banner.win)) banner = { text: snap.winner === "ALLY" ? "VICTORY" : "DEFEAT", color: snap.winner === "ALLY" ? "#2fa8ff" : "#e84057", t0: perfNow() + 1e9, win: true, big: true };
  if (banner && banner.win) banner.t0 = perfNow() - 600;   // hold the end-of-game banner
  if (sc) lastScore = JSON.parse(JSON.stringify(sc));

  updatePanel(snap);
  updateFeed(snap);
  updateScore(snap);
  statusEl.textContent = `live · t=${snap.time}s`;
  statusEl.className = "";
}

function updateScore(snap) {
  const sc = snap.score; if (!sc) return;
  const A = sc.ALLY, E = sc.ENEMY, $ = id => document.getElementById(id);
  $("sAllyK").textContent = `${A.kills} / ${A.deaths} / ${A.assists}`;
  $("sEnemyK").textContent = `${E.kills} / ${E.deaths} / ${E.assists}`;
  $("sAllyNx").style.width = `${(A.nexus_hp*100)|0}%`;
  $("sEnemyNx").style.width = `${(E.nexus_hp*100)|0}%`;
  $("sAllyGold").textContent = (A.gold/1000).toFixed(1) + "k";
  $("sEnemyGold").textContent = (E.gold/1000).toFixed(1) + "k";
  $("sAllyDrg").textContent = A.dragons || 0;
  $("sEnemyDrg").textContent = E.dragons || 0;
  const t = snap.time | 0;
  $("gametime").textContent = `${(t/60)|0}:${String(t%60).padStart(2,"0")}`;
  $("winner").textContent = snap.winner ? `${snap.winner} WINS` : "";
}

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

function updateFeed(snap) {
  const lines = snap.feed || [];
  const html = lines.map(l => `<div class="ln">${esc(l)}</div>`).join("");
  if (feedLines.innerHTML !== html) feedLines.innerHTML = html;
}

function updatePanel(snap) {
  const champs = snap.champions || [];
  const parts = [];
  for (const tm of ["ALLY", "ENEMY"]) {
    const list = champs.filter(c => c.team === tm);
    if (!list.length) continue;
    parts.push(`<div class="teamhdr ${tm === "ALLY" ? "ally" : "enemy"}">${tm === "ALLY" ? "Blue side · Ally" : "Red side · Enemy"}</div>`);
    for (const c of list) {
      const lr = c.learned || {};
      const fmt = arr => (arr || []).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ");
      let learnedHtml = "";
      if (lr.up && lr.up.length) learnedHtml += `<div class="learned up">learned+ ${esc(fmt(lr.up))}</div>`;
      if (lr.down && lr.down.length) learnedHtml += `<div class="learned dn">learned− ${esc(fmt(lr.down))}</div>`;
      const T = team(c.team);
      const idc = PARTICLE[c.name] || PARTICLE._default;
      const items = (c.items || []).map(n =>
        `<span class="item" title="${esc(n)}">${esc(n.split(" ").map(w => w[0]).join("").slice(0, 3))}</span>`).join("");
      parts.push(`
      <div class="champ ${c.team === "ALLY" ? "ally" : "enemy"}${c.alive ? "" : " dead"}">
        <div class="portrait" style="background:radial-gradient(circle at 35% 30%,rgb(${idc}),#0a0f14 85%);border-color:${T.main}">
          ${esc(c.name[0])}<span class="lv">${c.level}</span></div>
        <div class="row1"><span><span class="nm">${esc(c.name)}</span><span class="role">${esc(c.role)}</span></span>
          <span class="kda2${c.alive ? "" : " dead"}">${c.alive ? c.kills + " / " + c.deaths + " / " + c.assists
            : "☠ " + (c.dead_timer | 0) + "s"}</span></div>
        <div class="beh">${esc((c.behavior || "—").replace(" (gated)", ""))}</div>
        <div class="bars">
          <div class="hpbar"><div style="width:${(c.hp_frac * 100) | 0}%;background:linear-gradient(180deg,${T.hi},${T.main})"></div></div>
          <div class="mpbar"><div style="width:${((c.mp_frac ?? 0) * 100) | 0}%"></div></div>
        </div>
        <div class="meta"><span class="g">${c.gold}g</span>
          <span>AD <b>${c.ad || 0}</b></span><span>AP <b>${c.ap || 0}</b></span>
          <span>CS <b>${c.cs || 0}</b></span>
          ${items ? `<span class="items">${items}</span>` : ""}</div>
        ${learnedHtml}
      </div>`);
    }
  }
  champsPanel.innerHTML = parts.join("");
}

// ---- polling loop ----
async function poll() {
  try {
    const r = await fetch(`${SERVER}/state`, { cache: "no-store" });
    const snap = await r.json();
    render(snap);
  } catch (e) {
    statusEl.textContent = "server offline — run: python3 state_server.py";
    statusEl.className = "bad";
  }
}
setInterval(poll, POLL_MS);

// scenario switching (asks the server to reset to a scenario)
async function setScenario(name) {
  try { await fetch(`${SERVER}/scenario?name=${name}`, { cache: "no-store" }); }
  catch (e) {}
  lastScore = null; banner = null;
}
// camera toggle: action-follow vs. whole-map overview
const camBtn = document.getElementById("camBtn");
if (camBtn) camBtn.addEventListener("click", () => {
  autoCam = !autoCam;
  camBtn.textContent = autoCam ? "camera: action" : "camera: overview";
});

scenarioSel.addEventListener("change", () => setScenario(scenarioSel.value));
document.getElementById("reload").addEventListener("click",
  () => setScenario(scenarioSel.value));
