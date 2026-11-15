// renderer.js — draws the Python sim in a browser canvas.
//
// Polls the state server's /state each tick and renders champions, minions,
// the objective, and attack/cast effects. Smooth movement via interpolation.
// Right panel shows each champion's current AI behavior (the demo money shot).
//
// Server URL: same host, port 8765 by default. Change SERVER below if needed.

const SERVER = "http://127.0.0.1:8765";
const POLL_MS = 100;            // match the sim tick (10 Hz)

const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const descEl = document.getElementById("desc");
const champsPanel = document.getElementById("champs");
const feedLines = document.getElementById("feedlines");
const scenarioSel = document.getElementById("scenario");

const perfNow = () => performance.now();
let MAP = 15000;                // updated from server
const drawPos = {};             // name -> {x,y} smoothed screen-space (world units)
const fxFlashes = [];           // recent effects, fade over time
const feed = [];                // combat feed lines

function resize() {
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
}
window.addEventListener("resize", resize);
resize();

// ---- dynamic camera: follows + zooms into the main action ----
// cam.cx/cy = world point at screen center; cam.view = world units across the
// shorter screen axis (smaller = more zoomed in). Smoothed toward targets.
const cam = { cx: 7500, cy: 7500, view: MAP, tcx: 7500, tcy: 7500, tview: MAP };
let autoCam = true;   // toggle with the button; false = whole-map overview

const CLUSTER_RADIUS = 3500;   // champs within this of a seed are "together"
const PADDING = 2800;          // extra world units around the group (spacing)
const MIN_VIEW = 4500;         // never zoom in tighter than this (avoids blob)

function updateCamera(snap) {
  const champs = (snap.champions || []).filter(c => c.alive);
  if (!autoCam || champs.length === 0) {
    cam.tcx = MAP/2; cam.tcy = MAP/2; cam.tview = MAP;
  } else {
    // Find the champion whose neighborhood contains the MOST champions — that
    // is 'where the most people are' (the main action). Frame that group.
    let bestSeed = champs[0], bestCount = -1;
    for (const c of champs) {
      const cnt = champs.filter(o =>
        (o.x-c.x)**2 + (o.y-c.y)**2 < CLUSTER_RADIUS**2).length;
      if (cnt > bestCount) { bestCount = cnt; bestSeed = c; }
    }
    // the group = everyone near that seed; frame exactly them
    const group = champs.filter(o =>
      (o.x-bestSeed.x)**2 + (o.y-bestSeed.y)**2 < (CLUSTER_RADIUS*1.3)**2);
    let minx=1e9, miny=1e9, maxx=-1e9, maxy=-1e9, sx=0, sy=0;
    for (const c of group) {
      minx=Math.min(minx,c.x); maxx=Math.max(maxx,c.x);
      miny=Math.min(miny,c.y); maxy=Math.max(maxy,c.y);
      sx+=c.x; sy+=c.y;
    }
    cam.tcx = (minx+maxx)/2; cam.tcy = (miny+maxy)/2;
    // zoom to fit the group's extent + padding; MIN_VIEW stops it over-zooming
    // onto a tight pile (so you see spacing, not a blob)
    const extent = Math.max(maxx-minx, maxy-miny) + PADDING * 2;
    cam.tview = Math.max(MIN_VIEW, Math.min(MAP, extent));
  }
  // smooth toward targets so the camera glides
  cam.cx += (cam.tcx - cam.cx) * 0.07;
  cam.cy += (cam.tcy - cam.cy) * 0.07;
  cam.view += (cam.tview - cam.view) * 0.05;
}

// world (0..MAP, y-up) -> screen (pixels, y-down) through the camera
function toScreen(x, y) {
  const s = Math.min(canvas.width, canvas.height);
  const scale = s / cam.view;                       // px per world unit
  const sx = canvas.width / 2 + (x - cam.cx) * scale;
  const sy = canvas.height / 2 - (y - cam.cy) * scale;  // flip y (up = north)
  return [sx, sy];
}
function scalePx(units) {
  const s = Math.min(canvas.width, canvas.height);
  return units * (s / cam.view);
}

// ---- Summoner's Rift-ish background ----
function drawMap() {
  ctx.fillStyle = "#1c2c22"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const lane = "#3a3e30", river = "#28465f";
  const L = (x0,y0,x1,y1,w,col) => {
    const [ax,ay]=toScreen(x0,y0),[bx,by]=toScreen(x1,y1);
    ctx.strokeStyle=col; ctx.lineWidth=w; ctx.beginPath();
    ctx.moveTo(ax,ay); ctx.lineTo(bx,by); ctx.stroke();
  };
  const laneW = scalePx(1600);
  // three lanes (bottom, mid diagonal, top)
  L(600,600,14400,600,laneW,lane); L(14400,600,14400,14400,laneW,lane);
  L(600,600,600,14400,laneW,lane); L(600,14400,14400,14400,laneW,lane);
  L(1500,1500,13500,13500,laneW,lane);
  // river band (perpendicular diagonal)
  L(0,7500,7500,0,scalePx(1400),river); L(15000,7500,7500,15000,scalePx(1400),river);
  // bases
  const base = (x,y,col) => { const [sx,sy]=toScreen(x,y);
    ctx.fillStyle=col; ctx.beginPath(); ctx.arc(sx,sy,scalePx(1200),0,7); ctx.fill(); };
  base(1000,1000,"rgba(70,110,200,.35)"); base(14000,14000,"rgba(200,70,70,.35)");
}

function teamColor(team) { return team === "ALLY" ? "#4fa8ff" : "#ef5a5a"; }

function render(snap) {
  MAP = snap.map_size || MAP;
  descEl.textContent = snap.desc || "";
  updateCamera(snap);          // follow + zoom into the action
  drawMap();

  // objective
  {
    const o = snap.objective;
    const [x,y] = toScreen(o.x, o.y);
    ctx.fillStyle = o.up ? "#d49a3c" : "#555b68";
    ctx.beginPath(); ctx.arc(x, y, 9, 0, 7); ctx.fill();
    ctx.fillStyle = o.up ? "#d49a3c" : "#7a8092";
    ctx.font = "11px monospace"; ctx.textAlign = "center";
    ctx.fillText(o.up ? "DRAGON UP" : `dragon ${o.spawns_in|0}s`, x, y + 20);
  }

  // structures (towers + nexus) — drawn large/glowing so they're unmissable
  for (const s of snap.structures || []) {
    let [x,y] = toScreen(s.x, s.y);
    const isNexus = s.kind === "nexus";
    // nudge corner nexuses inward so they aren't clipped at the canvas edge
    if (isNexus) { x = Math.max(28, Math.min(canvas.width - 28, x));
                   y = Math.max(28, Math.min(canvas.height - 28, y)); }
    const col = s.team === "ALLY" ? "#4a7ad0" : "#d05a5a";
    if (!s.alive) {
      ctx.strokeStyle = "rgba(140,140,150,.6)"; ctx.lineWidth = 2;
      const r = isNexus ? 14 : 7;
      ctx.beginPath(); ctx.moveTo(x-r,y-r); ctx.lineTo(x+r,y+r);
      ctx.moveTo(x+r,y-r); ctx.lineTo(x-r,y+r); ctx.stroke();   // rubble X
      continue;
    }
    const sz = isNexus ? 18 : 8;
    if (isNexus) {                         // glow ring + pulse so it stands out
      const pulse = sz + 8 + 3 * Math.sin(perfNow() / 300);
      ctx.strokeStyle = col; ctx.globalAlpha = 0.5; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(x, y, pulse, 0, 7); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = col; ctx.fillRect(x - sz, y - sz, sz*2, sz*2);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.strokeRect(x-sz,y-sz,sz*2,sz*2);
    // hp bar above
    ctx.fillStyle = "#2a2e3a"; ctx.fillRect(x - sz, y - sz - 7, sz*2, 4);
    ctx.fillStyle = s.hp_frac > 0.3 ? "#6ad08a" : "#e05a5a";
    ctx.fillRect(x - sz, y - sz - 7, sz*2*s.hp_frac, 4);
    if (isNexus) {
      ctx.fillStyle = "#fff"; ctx.font = "bold 12px monospace"; ctx.textAlign = "center";
      ctx.fillText(`${s.team} NEXUS`, x, y + sz + 14);
    }
  }

  // minions
  for (const m of snap.minions || []) {
    const [x,y] = toScreen(m.x, m.y);
    ctx.fillStyle = m.team === "ALLY" ? "#4a6fcf" : "#cf5a5a";
    const s = m.kind === "siege" ? 4 : 2.5;
    ctx.fillRect(x - s, y - s, s * 2, s * 2);
  }

  // effects (projectiles that travel src->dst, then fade). Longer-lived and
  // thicker so you actually SEE the ranged attacks, not a 1-frame flash.
  for (const e of snap.fx || []) fxFlashes.push({ ...e, life: 1, age: 0 });
  for (let i = fxFlashes.length - 1; i >= 0; i--) {
    const e = fxFlashes[i];
    const [ax,ay] = toScreen(e.src_x, e.src_y), [bx,by] = toScreen(e.dst_x, e.dst_y);
    let col = "230,230,180";                 // auto-attack
    if (e.kind === "heal") col = "120,240,160";
    else if (e.kind === "cast") col = e.cc ? "240,220,90" : "190,110,250";
    // the trail line
    ctx.strokeStyle = `rgba(${col},${e.life * 0.9})`;
    ctx.lineWidth = e.kind === "cast" ? 3.5 : 2;
    ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by); ctx.stroke();
    // a moving projectile head along the line (reads as a ranged shot)
    const t = Math.min(1, e.age);
    const px = ax + (bx - ax) * t, py = ay + (by - ay) * t;
    ctx.fillStyle = `rgba(${col},${e.life})`;
    ctx.beginPath(); ctx.arc(px, py, e.kind === "cast" ? 5 : 3, 0, 7); ctx.fill();
    // impact flash at the target when it arrives
    if (t >= 1) {
      ctx.strokeStyle = `rgba(${col},${e.life})`; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(bx, by, 10 * (1 - e.life) + 6, 0, 7); ctx.stroke();
    }
    e.age += 0.25; e.life -= 0.045;          // slower fade -> visible ~0.5s
    if (e.life <= 0) fxFlashes.splice(i, 1);
  }

  // champions — move toward target at each champ's OWN speed (so fast champs
  // visibly outpace slow ones and it reads as walking, not teleport-gliding)
  const dtFrame = 1 / 30;                        // render step ~30fps
  for (const c of snap.champions || []) {
    if (!c.alive) continue;
    const p = drawPos[c.name] || { x: c.x, y: c.y, sx: 0, sy: 0, hp: c.hp_frac,
                                   hitFlash: 0, spawnFade: 0, atk: 0 };
    // move at the champion's real move speed (game units/sec), capped so we
    // never overshoot the server target. This makes per-champ speed VISIBLE.
    const dx = c.x - p.x, dy = c.y - p.y;
    const dist = Math.hypot(dx, dy);
    const speed = (c.move_speed || 330) * dtFrame * 1.15;  // slight lead on sim
    const stepLen = Math.min(speed, dist);
    const ox = p.x, oy = p.y;
    if (dist > 1e-3) { p.x += (dx / dist) * stepLen; p.y += (dy / dist) * stepLen; }
    p.sx = p.x - ox; p.sy = p.y - oy;            // actual velocity (for facing)
    // hit flash when hp dropped since last frame
    if (c.hp_frac < p.hp - 0.001) p.hitFlash = 1;
    p.hp = c.hp_frac;
    p.hitFlash = Math.max(0, p.hitFlash - 0.12);
    p.spawnFade = Math.min(1, p.spawnFade + 0.08);   // fade-in after (re)spawn
    drawPos[c.name] = p;

    const [x,y] = toScreen(p.x, p.y);
    const col = teamColor(c.team);
    const moving = Math.hypot(p.sx, p.sy) > 2;
    ctx.globalAlpha = p.spawnFade;

    // attack-range ring
    ctx.strokeStyle = "rgba(255,255,255,.07)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(x, y, scalePx(c.attack_range || 550), 0, 7); ctx.stroke();

    // attack animation: a brief scale-up pulse timed to the champ's attack
    // speed, so a fast attacker (Ashe) visibly pulses more often than a slow
    // one (Darius). `atk` ramps when attacking, decays otherwise.
    if (c.attacking) p.atk = Math.min(1, p.atk + 0.5 * (c.attack_speed || 0.7));
    else p.atk = Math.max(0, p.atk - 0.15);
    const atkPulse = 1 + 0.35 * p.atk;
    // subtle walk bob when moving (frequency scales with move speed)
    const bob = moving ? 1 + 0.1 * Math.sin(perfNow() / (12000 / (c.move_speed||330))) : 1;
    // champion radius: scaled with zoom but kept SMALL and capped so bodies
    // never cover the gaps between champions — you can see spacing. A champ is
    // ~120 world units across; we draw a bit under that and cap tightly.
    const baseR = Math.max(5, Math.min(11, scalePx(130)));
    const r = baseR * bob * atkPulse;

    // body (flash white on hit, orange tint while attacking)
    ctx.fillStyle = p.hitFlash > 0
      ? `rgba(255,255,255,${0.4 + 0.6 * p.hitFlash})`
      : (p.atk > 0.3 ? "#ffcf6a" : col);
    ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke();

    // facing indicator (a little nub in the movement direction)
    if (moving) {
      const m = Math.hypot(p.sx, p.sy);
      const fx = x + (p.sx / m) * (r + 4), fy = y - (p.sy / m) * (r + 4);
      ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(fx, fy); ctx.stroke();
    }

    if (c.cc > 0) {   // CC ring pulses
      const pulse = r + 4 + 2 * Math.sin(perfNow() / 80);
      ctx.strokeStyle = "#f0dc5a"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, pulse, 0, 7); ctx.stroke();
    }

    // name + hp bar, positioned relative to the (zoom-scaled) body radius
    const bw = Math.max(26, r * 2.4);            // hp-bar width tracks body size
    ctx.fillStyle = "#fff";
    ctx.font = `${Math.max(10, Math.min(14, r))}px monospace`;
    ctx.textAlign = "center";
    ctx.fillText(`${c.name} L${c.level}`, x, y - r - 6);
    const by = y + r + 4;
    ctx.fillStyle = "#3a3f4c"; ctx.fillRect(x - bw/2, by, bw, 4);
    const hpcol = c.hp_frac > 0.5 ? "#5fd27a" : c.hp_frac > 0.25 ? "#d4b24a" : "#e05a5a";
    ctx.fillStyle = hpcol; ctx.fillRect(x - bw/2, by, bw * c.hp_frac, 4);
    ctx.globalAlpha = 1;
  }

  // dead champs: respawn marker at base; reset fade so they fade in on revive
  for (const c of snap.champions || []) {
    if (c.alive) continue;
    if (drawPos[c.name]) drawPos[c.name].spawnFade = 0;
    const [x,y] = toScreen(c.spawn_x, c.spawn_y);
    ctx.fillStyle = "#7a8092"; ctx.font = "10px monospace"; ctx.textAlign = "center";
    ctx.fillText(`${c.name} \u2620 ${c.dead_timer|0}s`, x, y);
  }

  updatePanel(snap);
  updateFeed(snap);
  updateScore(snap);
  statusEl.textContent = `t=${snap.time}s  live`;
  statusEl.className = "";
}

function updateScore(snap) {
  const sc = snap.score; if (!sc) return;
  const A = sc.ALLY, E = sc.ENEMY;
  document.getElementById("sAllyK").textContent = `${A.kills}/${A.deaths}/${A.assists}`;
  document.getElementById("sEnemyK").textContent = `${E.kills}/${E.deaths}/${E.assists}`;
  document.getElementById("sAllyNx").textContent = `${(A.nexus_hp*100)|0}%`;
  document.getElementById("sEnemyNx").textContent = `${(E.nexus_hp*100)|0}%`;
  const wEl = document.getElementById("winner");
  wEl.textContent = snap.winner ? `${snap.winner} WINS` : "";
}

function updateFeed(snap) {
  const lines = snap.feed || [];
  feedLines.innerHTML = lines.map(l =>
    `<div class="ln">${l.replace(/</g, "&lt;")}</div>`).join("");
}

function updatePanel(snap) {
  champsPanel.innerHTML = "";
  for (const c of snap.champions || []) {
    const div = document.createElement("div");
    div.className = "champ";
    // "learned" drift: what this bot has adapted toward/away from
    const lr = c.learned || {};
    const fmt = arr => (arr || []).map(([k, v]) =>
      `${k} ${v > 0 ? "+" : ""}${v}`).join(", ");
    let learnedHtml = "";
    if ((lr.up && lr.up.length) || (lr.down && lr.down.length)) {
      learnedHtml = `<div class="meta" style="color:#8fd3a0">learned+ ${fmt(lr.up)}</div>` +
                    `<div class="meta" style="color:#d38f8f">learned- ${fmt(lr.down)}</div>`;
    }
    div.innerHTML = `
      <div class="row1"><span class="nm tag-${c.team}">${c.name}</span>
        <span class="meta">${c.alive ? "L"+c.level : "dead "+(c.dead_timer|0)+"s"}</span></div>
      <div class="beh">\u2192 ${c.behavior || "—"}</div>
      <div class="meta">${c.role} · hp ${(c.hp_frac*100|0)}%</div>
      <div class="hpbar"><div style="width:${(c.hp_frac*100)|0}%"></div></div>
      ${learnedHtml}`;
    champsPanel.appendChild(div);
  }
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
