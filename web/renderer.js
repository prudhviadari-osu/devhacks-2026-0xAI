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

// world (0..MAP, y-up) -> screen (pixels, y-down), fit as a square
function toScreen(x, y) {
  const s = Math.min(canvas.width, canvas.height);
  const ox = (canvas.width - s) / 2, oy = (canvas.height - s) / 2;
  return [ox + (x / MAP) * s, oy + (1 - y / MAP) * s];
}
function scalePx(units) {
  const s = Math.min(canvas.width, canvas.height);
  return (units / MAP) * s;
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

  // minions
  for (const m of snap.minions || []) {
    const [x,y] = toScreen(m.x, m.y);
    ctx.fillStyle = m.team === "ALLY" ? "#4a6fcf" : "#cf5a5a";
    const s = m.kind === "siege" ? 4 : 2.5;
    ctx.fillRect(x - s, y - s, s * 2, s * 2);
  }

  // effects (lines from src to dst), freshest = brightest
  for (const e of snap.fx || []) fxFlashes.push({ ...e, life: 1 });
  for (let i = fxFlashes.length - 1; i >= 0; i--) {
    const e = fxFlashes[i];
    const [ax,ay] = toScreen(e.src_x, e.src_y), [bx,by] = toScreen(e.dst_x, e.dst_y);
    let col = "230,230,180";                 // auto
    if (e.kind === "heal") col = "120,240,160";
    else if (e.kind === "cast") col = e.cc ? "240,220,90" : "200,120,240";
    ctx.strokeStyle = `rgba(${col},${e.life})`; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by); ctx.stroke();
    e.life -= 0.12; if (e.life <= 0) fxFlashes.splice(i, 1);
  }

  // champions (smoothed movement)
  for (const c of snap.champions || []) {
    if (!c.alive) continue;
    const p = drawPos[c.name] || { x: c.x, y: c.y };
    p.x += (c.x - p.x) * 0.3; p.y += (c.y - p.y) * 0.3;
    drawPos[c.name] = p;
    const [x,y] = toScreen(p.x, p.y);
    const col = teamColor(c.team);

    // attack-range ring
    ctx.strokeStyle = "rgba(255,255,255,.08)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(x, y, scalePx(c.attack_range || 550), 0, 7); ctx.stroke();

    // body
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, 9, 0, 7); ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke();
    if (c.cc > 0) { ctx.strokeStyle = "#f0dc5a"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 13, 0, 7); ctx.stroke(); }

    // name + hp bar
    ctx.fillStyle = "#fff"; ctx.font = "11px monospace"; ctx.textAlign = "center";
    ctx.fillText(`${c.name} L${c.level}`, x, y - 16);
    ctx.fillStyle = "#3a3f4c"; ctx.fillRect(x - 18, y + 12, 36, 4);
    ctx.fillStyle = "#5fd27a"; ctx.fillRect(x - 18, y + 12, 36 * c.hp_frac, 4);
  }

  // dead champs: respawn marker at base
  for (const c of snap.champions || []) {
    if (c.alive) continue;
    const [x,y] = toScreen(c.spawn_x, c.spawn_y);
    ctx.fillStyle = "#7a8092"; ctx.font = "10px monospace"; ctx.textAlign = "center";
    ctx.fillText(`${c.name} \u2620 ${c.dead_timer|0}s`, x, y);
  }

  updatePanel(snap);
  updateFeed(snap);
  statusEl.textContent = `t=${snap.time}s  live`;
  statusEl.className = "";
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
    div.innerHTML = `
      <div class="row1"><span class="nm tag-${c.team}">${c.name}</span>
        <span class="meta">${c.alive ? "L"+c.level : "dead "+(c.dead_timer|0)+"s"}</span></div>
      <div class="beh">\u2192 ${c.behavior || "—"}</div>
      <div class="meta">${c.role} · hp ${(c.hp_frac*100|0)}%</div>
      <div class="hpbar"><div style="width:${(c.hp_frac*100)|0}%"></div></div>`;
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
scenarioSel.addEventListener("change", () => setScenario(scenarioSel.value));
document.getElementById("reload").addEventListener("click",
  () => setScenario(scenarioSel.value));
