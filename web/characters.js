// characters.js — procedurally drawn, animated champion figures (original art).
//
// Pure presentation: given a champion name and animation state, draws a small
// 3/4-view fantasy character on the canvas. No game logic lives here.
//
//   drawCharacter(ctx, name, x, y, H, st)
//     x, y  : screen position of the FEET
//     H     : figure height in px
//     st    : { face:±1, walk:phase, moving:bool, atk:0..1, now:ms, team:"#hex",
//             hit:0..1 }

(function () {
  const OUT = "rgba(12,8,16,.9)";

  // ---- per-champion look (original designs, themed by archetype) ----
  const LOOKS = {
    Ashe:   { skin:"#f1d3bf", hair:"#e8eef5", hairStyle:"long", outfit:"#3d78b8", outfit2:"#1f3b63",
              trim:"#cfe8ff", head:"hood", hood:"#e9f2fb", back:"cape", cape:"#2f5f99", weapon:"bow",
              fx:"140,210,255" },
    Sona:   { skin:"#f3d6c6", hair:"#3fc7b8", hairStyle:"twin", outfit:"#2b67b5", outfit2:"#183c70",
              trim:"#f2d27a", robe:true, weapon:"harp", fx:"120,230,200" },
    Lux:    { skin:"#f6dccb", hair:"#ffe08a", hairStyle:"long", outfit:"#f3f0ea", outfit2:"#3c5ca8",
              trim:"#f2c94c", robe:true, weapon:"wand", fx:"255,240,140" },
    Jax:    { skin:"#7a5a9a", hair:null, outfit:"#5a3f86", outfit2:"#2b1f45", trim:"#e2b54a",
              head:"mask", eyes:"#ffe36a", weapon:"polearm", pauldrons:true, fx:"255,190,90" },
    Zac:    { blob:true, outfit:"#5fd06a", outfit2:"#2f8a3c", eyes:"#fff", fx:"150,230,120" },
    Darius: { skin:"#e2b9a0", hair:"#2a1d1a", outfit:"#7a1f24", outfit2:"#2a1517", trim:"#9aa2ad",
              head:"horns", back:"cape", cape:"#5a1218", weapon:"axe", pauldrons:true, scale:1.1,
              fx:"230,90,80" },
    Leona:  { skin:"#e9c2a6", hair:"#a8452a", hairStyle:"long", outfit:"#e2b54a", outfit2:"#7a5520",
              trim:"#fff2c4", head:"sunhelm", weapon:"swordshield", pauldrons:true, fx:"255,200,80" },
    Ahri:   { skin:"#f6d8c8", hair:"#2b1f3a", hairStyle:"long", outfit:"#c23a6e", outfit2:"#f3e9ee",
              trim:"#ffd1e3", head:"ears", back:"tails", robe:true, weapon:"orb", fx:"255,130,200" },
    Lulu:   { skin:"#c9a7e8", hair:"#b9f2ff", hairStyle:"short", outfit:"#6b3fa8", outfit2:"#3a2160",
              trim:"#ffd36a", head:"wizard", hat:"#8a4fd0", weapon:"staff", scale:0.8, fx:"200,160,255" },
    Ryze:   { skin:"#6f9ae0", hair:null, outfit:"#3a3f8a", outfit2:"#20234f", trim:"#e6c068",
              back:"scroll", robe:true, weapon:"book", beard:true, fx:"150,120,255" },
    _default:{ skin:"#e9c6a8", hair:"#5a3a22", hairStyle:"short", outfit:"#6b6f7a", outfit2:"#2e3138",
              trim:"#c8aa6e", weapon:"sword", fx:"220,220,230" },
  };

  function shape(ctx, fill, lw) {
    ctx.fillStyle = fill; ctx.fill();
    ctx.lineWidth = lw; ctx.strokeStyle = OUT; ctx.stroke();
  }
  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h);
  }
  function glow(ctx, x, y, r, rgb, a) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, `rgba(255,255,255,${a})`);
    g.addColorStop(0.3, `rgba(${rgb},${a})`);
    g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
  }

  // ---------------- back layer (behind body) ----------------
  function drawBack(ctx, L, u, st) {
    const sway = Math.sin(st.now / 260) * 0.15 + (st.moving ? 0.25 : 0);
    if (L.back === "cape") {
      ctx.beginPath();
      ctx.moveTo(-3.6*u, -15*u);
      ctx.quadraticCurveTo(-7*u - sway*4*u, -8*u, -6.5*u - sway*6*u, -1*u);
      ctx.lineTo(-1*u, -2*u);
      ctx.lineTo(2*u, -15*u);
      ctx.closePath();
      const g = ctx.createLinearGradient(0, -15*u, 0, 0);
      g.addColorStop(0, L.cape); g.addColorStop(1, shade(L.cape, -0.35));
      shape(ctx, g, 0.6*u);
    } else if (L.back === "tails") {
      for (let i = 0; i < 5; i++) {
        const a = -0.9 + i * 0.32 + Math.sin(st.now / 300 + i) * 0.12;
        ctx.save(); ctx.translate(-2*u, -9*u); ctx.rotate(a - Math.PI / 2 - 0.6);
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.quadraticCurveTo(-2.4*u, 5*u, 0, 10*u);
        ctx.quadraticCurveTo(2.6*u, 5*u, 0, 0);
        const g = ctx.createLinearGradient(0, 0, 0, 10*u);
        g.addColorStop(0, "#f3e9ee"); g.addColorStop(0.7, "#f6c7d8"); g.addColorStop(1, "#fff");
        shape(ctx, g, 0.5*u);
        ctx.restore();
      }
    } else if (L.back === "scroll") {
      ctx.save(); ctx.translate(-3.5*u, -13*u); ctx.rotate(-0.5);
      rrect(ctx, -1.6*u, -6*u, 3.2*u, 12*u, 1.2*u);
      shape(ctx, "#e8d6a8", 0.5*u);
      ctx.fillStyle = "#7a5520"; ctx.fillRect(-1.8*u, -6.4*u, 3.6*u, 1.2*u); ctx.fillRect(-1.8*u, 5.2*u, 3.6*u, 1.2*u);
      ctx.fillStyle = "rgba(90,140,255,.9)";
      for (let i = -3; i <= 3; i += 2) ctx.fillRect(-0.6*u, i*u, 1.2*u, 0.5*u);
      ctx.restore();
    }
  }

  function shade(hex, amt) {
    const n = parseInt(hex.slice(1), 16);
    let r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    const f = v => Math.max(0, Math.min(255, Math.round(amt < 0 ? v * (1 + amt) : v + (255 - v) * amt)));
    return `rgb(${f(r)},${f(g)},${f(b)})`;
  }

  // ---------------- legs / robe ----------------
  function drawLegs(ctx, L, u, st) {
    const sw = st.moving ? Math.sin(st.walk) : 0;
    if (L.robe) {
      // feet peeking under a flared robe
      for (const s of [-1, 1]) {
        ctx.beginPath(); ctx.ellipse(s * 1.6*u + sw * s * 1.2*u, -0.6*u, 1.6*u, 0.9*u, 0, 0, 7);
        shape(ctx, shade(L.outfit2, -0.3), 0.5*u);
      }
      ctx.beginPath();
      ctx.moveTo(-3.2*u, -9*u); ctx.lineTo(3.4*u, -9*u);
      ctx.lineTo(4.8*u + sw*0.6*u, -1*u); ctx.quadraticCurveTo(0, 0.2*u, -4.8*u + sw*0.6*u, -1*u);
      ctx.closePath();
      const g = ctx.createLinearGradient(0, -9*u, 0, 0);
      g.addColorStop(0, L.outfit); g.addColorStop(1, L.outfit2);
      shape(ctx, g, 0.6*u);
      ctx.strokeStyle = L.trim; ctx.lineWidth = 0.6*u;
      ctx.beginPath(); ctx.moveTo(-4.5*u + sw*0.6*u, -1.6*u); ctx.quadraticCurveTo(0, -0.4*u, 4.5*u + sw*0.6*u, -1.6*u); ctx.stroke();
      return;
    }
    for (const s of [-1, 1]) {   // back leg first
      ctx.save(); ctx.translate(s * 1.4*u, -8.5*u); ctx.rotate(sw * 0.55 * s);
      rrect(ctx, -1.3*u, 0, 2.6*u, 6.5*u, 1*u); shape(ctx, s < 0 ? shade(L.outfit2, -0.25) : L.outfit2, 0.5*u);
      rrect(ctx, -1.5*u, 5.6*u, 3.4*u, 2.4*u, 1*u); shape(ctx, "#3a2a1e", 0.5*u);
      ctx.restore();
    }
  }

  // ---------------- torso ----------------
  function drawTorso(ctx, L, u) {
    ctx.beginPath();
    ctx.moveTo(-3.8*u, -15.5*u); ctx.lineTo(3.8*u, -15.5*u);
    ctx.lineTo(3.2*u, -8.2*u); ctx.lineTo(-3.2*u, -8.2*u); ctx.closePath();
    const g = ctx.createLinearGradient(-4*u, 0, 4*u, 0);
    g.addColorStop(0, shade(L.outfit, -0.25)); g.addColorStop(0.6, L.outfit); g.addColorStop(1, shade(L.outfit, 0.15));
    shape(ctx, g, 0.6*u);
    // belt + chest trim
    ctx.fillStyle = L.trim; ctx.fillRect(-3.3*u, -9.8*u, 6.6*u, 1.1*u);
    ctx.fillStyle = shade(L.trim, -0.3); ctx.fillRect(-0.6*u, -10*u, 1.4*u, 1.5*u);
    ctx.strokeStyle = L.trim; ctx.lineWidth = 0.5*u;
    ctx.beginPath(); ctx.moveTo(-2*u, -15.3*u); ctx.lineTo(0.3*u, -12.5*u); ctx.lineTo(2.4*u, -15.3*u); ctx.stroke();
    if (L.pauldrons) {
      for (const s of [-1, 1]) {
        ctx.beginPath(); ctx.ellipse(s * 3.6*u, -15*u, 2.4*u, 1.6*u, s * 0.3, 0, 7);
        const pg = ctx.createLinearGradient(0, -16.6*u, 0, -13.4*u);
        pg.addColorStop(0, shade(L.trim, 0.3)); pg.addColorStop(1, shade(L.trim, -0.35));
        shape(ctx, pg, 0.5*u);
      }
    }
  }

  // ---------------- head ----------------
  function drawHead(ctx, L, u, st) {
    const hx = 0.4*u, hy = -19.4*u, hr = 4*u;
    // hair behind head
    if (L.hair && (L.hairStyle === "long" || L.hairStyle === "twin")) {
      ctx.beginPath();
      ctx.moveTo(hx - 3.8*u, hy - 1*u);
      ctx.quadraticCurveTo(hx - 5.5*u, hy + 5*u, hx - 3.5*u, hy + 8*u);
      ctx.lineTo(hx + 1*u, hy + 4*u); ctx.lineTo(hx + 3*u, hy - 2*u); ctx.closePath();
      shape(ctx, shade(L.hair, -0.1), 0.5*u);
      if (L.hairStyle === "twin") {
        const sw = Math.sin(st.now / 280) * 0.2;
        ctx.save(); ctx.translate(hx - 3*u, hy - 2*u); ctx.rotate(0.5 + sw);
        ctx.beginPath(); ctx.ellipse(0, 4*u, 1.6*u, 4.5*u, 0, 0, 7); shape(ctx, L.hair, 0.5*u);
        ctx.restore();
      }
    }
    // face
    ctx.beginPath(); ctx.arc(hx, hy, hr, 0, 7);
    const g = ctx.createRadialGradient(hx + 1*u, hy - 1.2*u, 0.5*u, hx, hy, hr);
    g.addColorStop(0, shade(L.skin, 0.15)); g.addColorStop(1, shade(L.skin, -0.18));
    shape(ctx, g, 0.6*u);
    // eyes
    const blink = (Math.floor(st.now / 120) % 37) === 0;
    ctx.fillStyle = L.eyes || "#1b1420";
    if (blink) { ctx.fillRect(hx + 1.1*u, hy - 0.2*u, 1*u, 0.3*u); ctx.fillRect(hx + 2.9*u, hy - 0.2*u, 0.8*u, 0.3*u); }
    else {
      ctx.beginPath(); ctx.ellipse(hx + 1.6*u, hy - 0.1*u, 0.5*u, 0.75*u, 0, 0, 7); ctx.fill();
      ctx.beginPath(); ctx.ellipse(hx + 3.3*u, hy - 0.1*u, 0.4*u, 0.7*u, 0, 0, 7); ctx.fill();
      if (!L.eyes) { ctx.fillStyle = "#fff"; ctx.fillRect(hx + 1.6*u, hy - 0.6*u, 0.3*u, 0.3*u); }
    }
    if (L.beard) {
      ctx.beginPath(); ctx.moveTo(hx - 0.5*u, hy + 2*u);
      ctx.quadraticCurveTo(hx + 2*u, hy + 7*u, hx + 3.6*u, hy + 1.6*u);
      shape(ctx, "#5a4a3a", 0.4*u);
    }
    // hair on top / fringe
    if (L.hair && L.hairStyle) {
      ctx.beginPath();
      ctx.arc(hx, hy - 0.3*u, hr + 0.3*u, Math.PI * 0.95, Math.PI * 2.05);
      ctx.quadraticCurveTo(hx + 2.5*u, hy - 2.5*u, hx + 1*u, hy - 1.8*u);
      ctx.quadraticCurveTo(hx - 1*u, hy - 2.6*u, hx - 3.5*u, hy + 0.5*u);
      ctx.closePath();
      shape(ctx, L.hair, 0.5*u);
    }
    // headgear
    switch (L.head) {
      case "hood": {
        ctx.beginPath();
        ctx.moveTo(hx - 4.8*u, hy + 3.5*u);
        ctx.quadraticCurveTo(hx - 5.8*u, hy - 5.5*u, hx + 0.5*u, hy - 5.4*u);
        ctx.quadraticCurveTo(hx + 4.8*u, hy - 5*u, hx + 4.6*u, hy - 1.4*u);
        ctx.quadraticCurveTo(hx + 1.5*u, hy - 3.4*u, hx - 2.6*u, hy + 0.2*u);
        ctx.lineTo(hx - 2.6*u, hy + 3.8*u); ctx.closePath();
        shape(ctx, L.hood, 0.6*u);
        break;
      }
      case "mask": {
        ctx.beginPath(); ctx.arc(hx, hy, hr + 0.4*u, 0, 7); shape(ctx, L.outfit, 0.6*u);
        ctx.fillStyle = "#1a1228"; rrect(ctx, hx - 0.2*u, hy - 1.2*u, 4.8*u, 2.2*u, 1*u); ctx.fill();
        ctx.fillStyle = L.eyes; ctx.shadowColor = L.eyes; ctx.shadowBlur = 6;
        ctx.fillRect(hx + 1*u, hy - 0.5*u, 1.2*u, 0.7*u); ctx.fillRect(hx + 3*u, hy - 0.5*u, 1*u, 0.7*u);
        ctx.shadowBlur = 0;
        break;
      }
      case "horns": {
        ctx.beginPath(); ctx.arc(hx, hy - 0.5*u, hr + 0.5*u, Math.PI, Math.PI * 2);
        ctx.lineTo(hx + 4.5*u, hy + 0.6*u); ctx.lineTo(hx - 4.5*u, hy + 0.6*u); ctx.closePath();
        shape(ctx, "#5c636e", 0.6*u);
        ctx.fillStyle = "#1a1418"; ctx.fillRect(hx + 0.8*u, hy - 0.6*u, 3.6*u, 1*u);
        for (const s of [-1, 1]) {
          ctx.beginPath(); ctx.moveTo(hx + s*3*u, hy - 3.5*u);
          ctx.quadraticCurveTo(hx + s*6.5*u, hy - 5*u, hx + s*6*u, hy - 8.5*u);
          ctx.quadraticCurveTo(hx + s*4.8*u, hy - 5.8*u, hx + s*1.8*u, hy - 4.6*u); ctx.closePath();
          shape(ctx, "#e8e0cc", 0.5*u);
        }
        break;
      }
      case "sunhelm": {
        const t = st.now / 1500;
        ctx.save(); ctx.translate(hx - 0.5*u, hy - 3.5*u);
        for (let i = 0; i < 9; i++) {
          const a = Math.PI + (i / 8) * Math.PI;
          ctx.beginPath(); ctx.moveTo(Math.cos(a - 0.12) * 3*u, Math.sin(a - 0.12) * 3*u);
          ctx.lineTo(Math.cos(a) * (6 + Math.sin(t + i) * 0.4)*u, Math.sin(a) * (6 + Math.sin(t + i) * 0.4)*u);
          ctx.lineTo(Math.cos(a + 0.12) * 3*u, Math.sin(a + 0.12) * 3*u); ctx.closePath();
          shape(ctx, "#ffd76a", 0.35*u);
        }
        ctx.restore();
        ctx.beginPath(); ctx.arc(hx, hy - 0.4*u, hr + 0.5*u, Math.PI * 1.02, Math.PI * 1.98);
        ctx.lineTo(hx + 4.4*u, hy - 0.6*u); ctx.lineTo(hx - 4.4*u, hy - 0.6*u); ctx.closePath();
        shape(ctx, "#e2b54a", 0.5*u);
        break;
      }
      case "ears": {
        for (const [ox, rot] of [[-2.6, -0.35], [1.8, 0.3]]) {
          ctx.save(); ctx.translate(hx + ox*u, hy - 3.2*u); ctx.rotate(rot);
          ctx.beginPath(); ctx.moveTo(-1.6*u, 0); ctx.lineTo(0, -4.2*u); ctx.lineTo(1.6*u, 0); ctx.closePath();
          shape(ctx, L.hair, 0.5*u);
          ctx.beginPath(); ctx.moveTo(-0.8*u, -0.3*u); ctx.lineTo(0, -2.8*u); ctx.lineTo(0.8*u, -0.3*u); ctx.closePath();
          ctx.fillStyle = "#f6b3cc"; ctx.fill();
          ctx.restore();
        }
        break;
      }
      case "wizard": {
        const wob = Math.sin(st.now / 350) * 0.15;
        ctx.save(); ctx.translate(hx - 0.3*u, hy - 2.6*u);
        ctx.beginPath(); ctx.ellipse(0, 0, 6*u, 1.6*u, 0, 0, 7); shape(ctx, L.hat, 0.5*u);
        ctx.beginPath(); ctx.moveTo(-3.6*u, -0.3*u);
        ctx.quadraticCurveTo(-1*u, -6*u, -3.5*u + wob*8*u, -10*u);
        ctx.quadraticCurveTo(1*u, -6*u, 3.6*u, -0.3*u); ctx.closePath();
        shape(ctx, L.hat, 0.5*u);
        ctx.fillStyle = L.trim; ctx.fillRect(-3.4*u, -1.4*u, 6.8*u, 1*u);
        ctx.restore();
        break;
      }
    }
  }

  // ---------------- arm + held weapon ----------------
  function drawArm(ctx, L, u, st, front) {
    const sw = st.moving ? Math.sin(st.walk) : 0;
    const melee = ["axe", "polearm", "sword", "swordshield"].includes(L.weapon);
    let ang;
    if (front) {
      const chop = melee ? Math.sin(st.now / 85) * 0.9 * st.atk : 0;
      ang = (0.25 - sw * 0.45) * (1 - st.atk) + (-1.5 + chop) * st.atk;
    } else ang = 0.15 + sw * 0.45;
    ctx.save();
    ctx.translate(front ? 3*u : -3*u, -14.6*u);
    ctx.rotate(-ang);
    rrect(ctx, -1.1*u, -0.6*u, 2.2*u, 6.4*u, 1*u);
    shape(ctx, front ? L.outfit : shade(L.outfit, -0.3), 0.5*u);
    ctx.beginPath(); ctx.arc(0, 6.2*u, 1.2*u, 0, 7); shape(ctx, L.skin, 0.4*u);
    if (front) drawWeapon(ctx, L, u, st);
    else if (L.weapon === "swordshield") drawShield(ctx, L, u);
    ctx.restore();
  }

  function drawShield(ctx, L, u) {
    ctx.save(); ctx.translate(0, 6*u);
    ctx.beginPath(); ctx.arc(0, 0, 4.4*u, 0, 7);
    const g = ctx.createRadialGradient(-1*u, -1*u, 0.5*u, 0, 0, 4.4*u);
    g.addColorStop(0, "#fff2c4"); g.addColorStop(0.5, "#e2b54a"); g.addColorStop(1, "#8a6420");
    shape(ctx, g, 0.6*u);
    ctx.beginPath(); ctx.arc(0, 0, 1.8*u, 0, 7); shape(ctx, "#fff7d6", 0.4*u);
    ctx.restore();
  }

  function drawWeapon(ctx, L, u, st) {
    ctx.save(); ctx.translate(0, 6.2*u);
    const pulse = 0.6 + 0.4 * Math.sin(st.now / 140);
    switch (L.weapon) {
      case "bow": {
        ctx.rotate(Math.PI / 2 * st.atk);
        ctx.strokeStyle = "#cfe8ff"; ctx.lineWidth = 1.1*u;
        ctx.beginPath(); ctx.arc(-1.5*u, 0, 6*u, -1.25, 1.25); ctx.stroke();
        ctx.strokeStyle = OUT; ctx.lineWidth = 0.35*u;
        ctx.beginPath(); ctx.arc(-1.5*u, 0, 6.6*u, -1.25, 1.25); ctx.stroke();
        const pull = st.atk * 2.5*u;
        const ex = -1.5*u + Math.cos(1.25) * 6*u, ey = Math.sin(1.25) * 6*u;
        ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 0.3*u;
        ctx.beginPath(); ctx.moveTo(ex, -ey); ctx.lineTo(ex - pull, 0); ctx.lineTo(ex, ey); ctx.stroke();
        if (st.atk > 0.2) {
          ctx.strokeStyle = "#bfe6ff"; ctx.lineWidth = 0.5*u;
          ctx.beginPath(); ctx.moveTo(ex - pull, 0); ctx.lineTo(ex - pull + 8*u, 0); ctx.stroke();
          glow(ctx, ex - pull + 8*u, 0, 2.5*u, L.fx, 0.9 * st.atk);
        }
        break;
      }
      case "polearm": case "staff": {
        ctx.rotate(-0.25);
        const len = L.weapon === "staff" ? 11 : 15;
        rrect(ctx, -0.55*u, -len*u + 3*u, 1.1*u, len*u, 0.5*u);
        shape(ctx, L.weapon === "staff" ? "#8a5a2a" : "#6a6f78", 0.4*u);
        if (L.weapon === "polearm") {
          ctx.beginPath(); ctx.moveTo(-1.6*u, -len*u + 3*u); ctx.lineTo(0, -len*u - 1*u); ctx.lineTo(1.6*u, -len*u + 3*u); ctx.closePath();
          shape(ctx, "#ffe08a", 0.4*u);
          glow(ctx, 0, -len*u + 1*u, 3.5*u, L.fx, 0.35 + 0.5 * st.atk);
        } else {
          glow(ctx, 0, -len*u + 2.5*u, 3.6*u * pulse, L.fx, 0.85);
          ctx.beginPath(); ctx.arc(0, -len*u + 2.5*u, 1.1*u, 0, 7); shape(ctx, "#fff6c8", 0.3*u);
        }
        break;
      }
      case "axe": {
        ctx.rotate(-0.4);
        rrect(ctx, -0.6*u, -11*u, 1.2*u, 14*u, 0.5*u); shape(ctx, "#4a3426", 0.4*u);
        ctx.beginPath();
        ctx.moveTo(0.4*u, -11*u); ctx.quadraticCurveTo(6.5*u, -12*u, 6.2*u, -6.5*u);
        ctx.quadraticCurveTo(3.8*u, -8*u, 0.4*u, -6.4*u); ctx.closePath();
        const g = ctx.createLinearGradient(0, -12*u, 6*u, -6*u);
        g.addColorStop(0, "#e9edf2"); g.addColorStop(1, "#7a828e");
        shape(ctx, g, 0.5*u);
        ctx.beginPath(); ctx.moveTo(-0.4*u, -10.5*u); ctx.lineTo(-3*u, -9.5*u); ctx.lineTo(-0.4*u, -7.5*u); ctx.closePath();
        shape(ctx, "#9aa2ad", 0.4*u);
        if (st.atk > 0.3) glow(ctx, 4*u, -9*u, 5*u, "255,80,60", 0.4 * st.atk);
        break;
      }
      case "sword": case "swordshield": {
        ctx.rotate(-0.3);
        ctx.fillStyle = "#c8aa6e"; ctx.fillRect(-2*u, -1.2*u, 4*u, 0.9*u);
        ctx.beginPath(); ctx.moveTo(-0.8*u, -1.2*u); ctx.lineTo(-0.8*u, -10*u); ctx.lineTo(0, -11.5*u);
        ctx.lineTo(0.8*u, -10*u); ctx.lineTo(0.8*u, -1.2*u); ctx.closePath();
        shape(ctx, "#eef2f6", 0.4*u);
        if (L.weapon === "swordshield") glow(ctx, 0, -6*u, 5*u, L.fx, 0.25 + 0.5 * st.atk);
        break;
      }
      case "wand": {
        ctx.rotate(-0.5);
        rrect(ctx, -0.45*u, -6*u, 0.9*u, 7*u, 0.4*u); shape(ctx, "#f2f0ea", 0.3*u);
        glow(ctx, 0, -6.5*u, (3 + 3 * st.atk) * u * pulse, L.fx, 0.95);
        star(ctx, 0, -6.5*u, 1.4*u, "#fff7c8");
        break;
      }
      case "orb": {
        const oy = -3*u + Math.sin(st.now / 300) * 0.8*u;
        glow(ctx, 2*u, oy, (3.5 + 3 * st.atk) * u, L.fx, 0.9);
        ctx.beginPath(); ctx.arc(2*u, oy, 1.4*u, 0, 7); ctx.fillStyle = "#fff0f8"; ctx.fill();
        break;
      }
      case "book": {
        ctx.rotate(-0.2);
        rrect(ctx, -2.2*u, -2*u, 4.4*u, 3.2*u, 0.4*u); shape(ctx, "#5a2f86", 0.4*u);
        ctx.fillStyle = "#e6c068"; ctx.fillRect(-2*u, -0.6*u, 4*u, 0.4*u);
        if (st.atk > 0.1) {
          for (let i = 0; i < 3; i++) {
            const a = st.now / 200 + i * 2.1;
            glow(ctx, Math.cos(a) * 3*u, -3*u + Math.sin(a) * 1.5*u, 1.8*u, L.fx, 0.8 * st.atk);
          }
        }
        glow(ctx, 0, -2*u, 3*u, L.fx, 0.35);
        break;
      }
      case "harp": break;   // harp floats in front of the body (drawn separately)
    }
    ctx.restore();
  }

  function star(ctx, x, y, r, col) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r;
      ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
    }
    ctx.closePath(); ctx.fillStyle = col; ctx.fill();
  }

  function drawHarp(ctx, L, u, st) {
    const fy = Math.sin(st.now / 380) * 1*u;
    ctx.save(); ctx.translate(6.5*u, -12*u + fy); ctx.rotate(0.15);
    glow(ctx, 0, 0, (5 + 3 * st.atk) * u, L.fx, 0.45);
    ctx.beginPath();
    ctx.moveTo(-2.6*u, 4*u); ctx.quadraticCurveTo(-3.5*u, -2*u, 0, -4.5*u);
    ctx.quadraticCurveTo(3.4*u, -3*u, 2.6*u, 4*u); ctx.lineTo(-2.6*u, 4*u);
    ctx.strokeStyle = "#f2d27a"; ctx.lineWidth = 0.9*u; ctx.stroke();
    ctx.strokeStyle = "rgba(220,255,250,.9)"; ctx.lineWidth = 0.22*u;
    for (let i = -1; i <= 1; i++) {
      const vib = st.atk > 0.1 ? Math.sin(st.now / 30 + i) * 0.3*u : 0;
      ctx.beginPath(); ctx.moveTo(i * 1.1*u + vib, -2.6*u); ctx.lineTo(i * 1.1*u - vib, 4*u); ctx.stroke();
    }
    ctx.restore();
  }

  // ---------------- blob body (Zac) ----------------
  function drawBlob(ctx, L, u, st) {
    const sq = st.moving ? Math.sin(st.walk * 2) * 0.12 : Math.sin(st.now / 400) * 0.05;
    const w = 8*u * (1 + sq), h = 9*u * (1 - sq);
    ctx.save(); ctx.translate(0, -h);
    ctx.beginPath();
    for (let i = 0; i <= 24; i++) {
      const a = i / 24 * Math.PI * 2;
      const wob = 1 + 0.06 * Math.sin(a * 5 + st.now / 160);
      ctx.lineTo(Math.cos(a) * w * wob, Math.sin(a) * h * wob * (a > 0 && a < Math.PI ? 1 : 1.12));
    }
    ctx.closePath();
    const g = ctx.createRadialGradient(-2*u, -4*u, 1*u, 0, 0, w * 1.1);
    g.addColorStop(0, "#c8ffb0"); g.addColorStop(0.45, L.outfit); g.addColorStop(1, L.outfit2);
    ctx.globalAlpha *= 0.95; shape(ctx, g, 0.7*u);
    // inner goo bubbles
    ctx.fillStyle = "rgba(220,255,200,.35)";
    for (let i = 0; i < 4; i++) {
      const a = st.now / 700 + i * 1.6;
      ctx.beginPath(); ctx.arc(Math.cos(a) * w * 0.5, Math.sin(a * 1.3) * h * 0.4, (0.6 + i * 0.25) * u, 0, 7); ctx.fill();
    }
    // face
    ctx.fillStyle = "#fff";
    ctx.beginPath(); ctx.ellipse(2*u, -3*u, 1.5*u, 2*u, 0, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.ellipse(5*u, -3*u, 1.3*u, 1.8*u, 0, 0, 7); ctx.fill();
    ctx.fillStyle = "#14301a";
    ctx.beginPath(); ctx.arc(2.6*u, -2.8*u, 0.7*u, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(5.5*u, -2.8*u, 0.6*u, 0, 7); ctx.fill();
    ctx.strokeStyle = "#14301a"; ctx.lineWidth = 0.6*u;
    ctx.beginPath(); ctx.arc(3.8*u, 0.2*u, 2*u * (1 + st.atk * 0.5), 0.2, Math.PI - 0.2); ctx.stroke();
    // stretchy arm on attack
    if (st.atk > 0.1) {
      ctx.strokeStyle = L.outfit; ctx.lineWidth = 2.4*u; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(w * 0.8, 1*u); ctx.lineTo(w * 0.8 + 7*u * st.atk, -1*u); ctx.stroke();
      ctx.beginPath(); ctx.arc(w * 0.8 + 7*u * st.atk, -1*u, 2*u, 0, 7); shape(ctx, "#8ff08a", 0.5*u);
    }
    ctx.restore();
  }

  // ---------------- public entry ----------------
  window.drawCharacter = function (ctx, name, x, y, H, st) {
    const L = LOOKS[name] || LOOKS._default;
    const u = H / 24 * (L.scale || 1);
    const bob = st.moving ? Math.abs(Math.sin(st.walk)) * 0.8*u : Math.sin(st.now / 500) * 0.25*u;
    ctx.save();
    ctx.translate(x, y - bob);
    ctx.scale(st.face < 0 ? -1 : 1, 1);
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    // team rim light so allegiance reads at a glance
    ctx.shadowColor = st.team; ctx.shadowBlur = 5;
    if (L.blob) drawBlob(ctx, L, u, st);
    else {
      drawBack(ctx, L, u, st);
      drawArm(ctx, L, u, st, false);
      drawLegs(ctx, L, u, st);
      drawTorso(ctx, L, u);
      drawHead(ctx, L, u, st);
      if (L.weapon === "harp") drawHarp(ctx, L, u, st);
      drawArm(ctx, L, u, st, true);
    }
    ctx.shadowBlur = 0;
    if (st.hit > 0) {   // white hit flash
      ctx.globalCompositeOperation = "lighter";
      glow(ctx, 0, -11*u, 10*u, "255,255,255", 0.55 * st.hit);
    }
    ctx.restore();
  };
  window.characterHeight = name => 24 * ((LOOKS[name] || LOOKS._default).scale || 1);
})();
