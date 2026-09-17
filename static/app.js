/* ============================================================
   東方幻想夜行 · Midnight Youkai Radio — player logic
   scene art · tachometer · danmaku analyser · station data
   ============================================================ */

(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /* encoder + icecast pipeline delay: the needle should never finish before
     the music does, so we keep the clock a hair behind the true on-air time */
  const PIPELINE_LAG_S = 2.2;

  const state = {
    station: null,
    now: null,
    progress: { elapsed: 0, duration: 0 },
    online: false,
    playing: false,
    accent: '#ff5c8a',
    energy: 0,
    bass: 0,
    spectrum: new Float32Array(64),
    lastKey: '',
    measuredLag: null,
    userPaused: false,
    everPlayed: false,
    retries: 0,
    reconnectTimer: null,
    calib: null,
    lastMarkerEpoch: 0,
    sync: null,
    typers: [],
  };

  /* ------------------------------------------------------------ helpers */
  function fmtTime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }
  function hexToRgb(hex) {
    const h = (hex || '#ff5c8a').replace('#', '');
    const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
  }
  const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };
  const mixHex = (a, b, t) => {
    const A = hexToRgb(a), B = hexToRgb(b);
    return '#' + A.map((n, i) => Math.round(n + (B[i] - n) * t).toString(16).padStart(2, '0')).join('');
  };
  const lerp = (a, b, t) => a + (b - a) * t;

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(url + ' → ' + res.status);
    return res.json();
  }

  /* ------------------------------------------------------------ i18n */
  const LANG = /^\/(cn|zh)(\/|$)/.test(location.pathname) ? 'zh' : 'en';
  const ZH = LANG === 'zh';

  const I18N = {
    en: {
      title: '東方幻想夜行 · Midnight Youkai Radio',
      onair: 'NOW ON AIR', listeners: 'LISTENERS', elapsed: 'ELAPSED', gear: 'GEAR',
      length: 'LENGTH', volume: 'THROTTLE',
      upnext: 'UP NEXT <span class="jp">次の曲</span>',
      driftlog: 'DRIFT LOG <span class="jp">走行記録</span>',
      viz: 'DANMAKU ANALYSER <span class="jp">弾幕</span>',
      footer: '東方 PROJECT × EUROBEAT · 深夜の峠 · 幻想郷から生放送',
      live: 'LIVE', offline: 'OFFLINE', connecting: 'CONNECTING',
      ignition: 'IGNITION', locked: 'LOCKED', idle: 'IDLE', energy: 'ENERGY',
      replay: 'REPLAY', novoice: 'NO VOICE', quiet: '…quiet on the mountain for a moment…',
      djrole: 'NIGHT SPARROW · DJ', switchTo: '中文', other: '/cn',
    },
    zh: {
      title: '東方幻想夜行 · 中文台｜东方 Eurobeat 电台',
      onair: '正在播出', listeners: '在听', elapsed: '已播', gear: '挡位',
      length: '时长', volume: '音量',
      upnext: '下一首 <span class="jp">待播</span>',
      driftlog: '走行记录 <span class="jp">刚播过</span>',
      viz: '弹幕频谱 <span class="jp">弹幕</span>',
      footer: '东方 PROJECT × EUROBEAT · 午夜山道 · 以幻想乡之名直播',
      live: '直播中', offline: '离线', connecting: '连接中',
      ignition: '点火', locked: '已锁定', idle: '待机', energy: '能量',
      replay: '重播', novoice: '无声', quiet: '……山上安静了一会儿……',
      djrole: '夜雀 · 电台 DJ', switchTo: 'EN', other: '/',
    },
  };

  function t(key) {
    const table = I18N[LANG] || I18N.en;
    if (table[key] != null) return table[key];
    return I18N.en[key] != null ? I18N.en[key] : key;
  }

  function api(path) {
    return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'lang=' + LANG;
  }

  function applyI18n() {
    document.documentElement.lang = ZH ? 'zh-CN' : 'en';
    document.title = t('title');
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.innerHTML = t(el.getAttribute('data-i18n'));
    });
    const sw = document.getElementById('lang-switch');
    if (sw) {
      sw.textContent = t('switchTo');
      sw.setAttribute('href', t('other'));
    }
  }

  /* ============================================================ scene */
  const Scene = (() => {
    const canvas = $('scene');
    const ctx = canvas.getContext('2d');
    let W = 0, H = 0, dpr = 1;
    let stars = [], petals = [], clouds = [], hills = [], smokes = [], bullets = [];
    let smokeTimer = 0;

    function seeded(n) { const x = Math.sin(n * 12.9898) * 43758.5453; return x - Math.floor(x); }

    function build() {
      const rnd = (i) => seeded(i * 7.77 + 1.13);
      stars = Array.from({ length: 220 }, (_, i) => ({
        x: rnd(i) * W,
        y: rnd(i + 900) * H * 0.72,
        r: 0.4 + rnd(i + 300) * 1.5,
        a: 0.25 + rnd(i + 600) * 0.75,
        ph: rnd(i + 1200) * 6.28,
      }));
      petals = Array.from({ length: 44 }, (_, i) => ({
        x: rnd(i + 40) * W,
        y: rnd(i + 60) * H,
        vx: 0.12 + rnd(i + 80) * 0.4,
        vy: 0.25 + rnd(i + 100) * 0.55,
        s: 3.6 + rnd(i + 140) * 6.4,
        rot: rnd(i + 160) * 6.28,
        vr: (rnd(i + 180) - 0.5) * 0.02,
        a: 0.22 + rnd(i + 200) * 0.5,
      }));
      clouds = Array.from({ length: 7 }, (_, i) => ({
        x: rnd(i + 240) * W,
        y: H * (0.16 + rnd(i + 260) * 0.34),
        w: W * (0.16 + rnd(i + 280) * 0.34),
        h: 10 + rnd(i + 300) * 26,
        v: 0.06 + rnd(i + 320) * 0.16,
        a: 0.05 + rnd(i + 340) * 0.1,
      }));
      hills = [0, 1, 2].map((layer) => {
        const base = H * (0.52 + layer * 0.1);
        const pts = [];
        const n = 42;
        for (let i = 0; i <= n; i++) {
          const x = (i / n) * W;
          const h1 = Math.sin(i * 0.6 + layer * 2.1) * 26 * (1 - layer * 0.2);
          const h2 = Math.sin(i * 1.9 + layer * 4.7) * 14;
          const h3 = (seeded(i * 3.3 + layer * 11) - 0.5) * 34;
          pts.push([x, base - h1 - h2 - h3 - (layer === 0 ? 40 : layer === 1 ? 22 : 8)]);
        }
        return pts;
      });
      bullets = Array.from({ length: 12 }, (_, i) => ({
        ang: (i / 12) * 6.28,
        r: 0.62 + seeded(i * 5.1) * 0.5,
        s: 0.18 + seeded(i * 2.3) * 0.3,
        br: 2 + seeded(i * 9.1) * 3,
        hue: i % 3 === 0 ? '#4fe3ff' : i % 3 === 1 ? '#ff2e4d' : '#ffd166',
      }));
    }

    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
    }

    function drawSky(t) {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, '#03040a');
      g.addColorStop(0.34, '#070b1e');
      g.addColorStop(0.62, '#151033');
      g.addColorStop(0.78, '#38122f');
      g.addColorStop(1, '#0a0714');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);

      const neb = ctx.createRadialGradient(W * 0.78, H * 0.2, 0, W * 0.78, H * 0.2, W * 0.5);
      neb.addColorStop(0, 'rgba(255,46,77,0.14)');
      neb.addColorStop(0.5, 'rgba(120,40,140,0.06)');
      neb.addColorStop(1, 'transparent');
      ctx.fillStyle = neb;
      ctx.fillRect(0, 0, W, H);

      for (const s of stars) {
        const tw = 0.55 + 0.45 * Math.sin(t * 0.0012 + s.ph);
        ctx.globalAlpha = s.a * tw;
        ctx.fillStyle = s.r > 1.3 ? '#cfe4ff' : '#ffffff';
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function drawMoon(t) {
      const cx = W * (W < 820 ? 0.78 : 0.83);
      const cy = H * 0.2;
      const r = Math.min(W, H) * (W < 820 ? 0.085 : 0.105);
      const halo = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r * 4.4);
      halo.addColorStop(0, 'rgba(255,90,120,0.30)');
      halo.addColorStop(0.36, 'rgba(255,46,77,0.10)');
      halo.addColorStop(1, 'transparent');
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 4.4, 0, 6.2832);
      ctx.fill();

      const mg = ctx.createRadialGradient(cx - r * 0.34, cy - r * 0.34, r * 0.1, cx, cy, r);
      mg.addColorStop(0, '#ffe3ea');
      mg.addColorStop(0.42, '#ff6f89');
      mg.addColorStop(0.82, '#c2132f');
      mg.addColorStop(1, '#67091c');
      ctx.fillStyle = mg;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 6.2832);
      ctx.fill();

      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 6.2832);
      ctx.clip();
      ctx.fillStyle = 'rgba(80,6,20,0.28)';
      [[-0.32, -0.18, 0.2], [0.24, 0.1, 0.15], [0.05, 0.42, 0.11], [-0.5, 0.36, 0.09]].forEach(([dx, dy, dr]) => {
        ctx.beginPath();
        ctx.arc(cx + dx * r, cy + dy * r, dr * r, 0, 6.2832);
        ctx.fill();
      });
      ctx.restore();

      ctx.save();
      ctx.strokeStyle = 'rgba(255,214,224,0.5)';
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 12]);
      ctx.beginPath();
      ctx.arc(cx, cy, r * 1.55 + Math.sin(t * 0.0004) * 8, 0, 6.2832);
      ctx.stroke();
      ctx.restore();

      for (const b of bullets) {
        const ang = b.ang + t * 0.00009 * b.s * 6;
        const bx = cx + Math.cos(ang) * r * b.r * 2.05;
        const by = cy + Math.sin(ang) * r * b.r * 1.5;
        ctx.fillStyle = rgba(b.hue, 0.75);
        ctx.shadowColor = b.hue;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(bx, by, b.br, 0, 6.2832);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }

    function drawClouds(t) {
      for (const c of clouds) {
        c.x += c.v;
        if (c.x > W + c.w) c.x = -c.w;
        const g = ctx.createLinearGradient(c.x, c.y, c.x, c.y + c.h);
        g.addColorStop(0, `rgba(255,120,150,${c.a})`);
        g.addColorStop(0.7, `rgba(90,60,140,${c.a * 0.6})`);
        g.addColorStop(1, 'transparent');
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.ellipse(c.x, c.y, c.w * 0.5, c.h * 0.5, 0, 0, 6.2832);
        ctx.fill();
      }
    }

    function drawHills() {
      hills.forEach((pts, i) => {
        ctx.beginPath();
        ctx.moveTo(0, H);
        pts.forEach(([x, y]) => ctx.lineTo(x, y));
        ctx.lineTo(W, H);
        ctx.closePath();
        ctx.fillStyle = i === 0 ? 'rgba(9,11,26,0.92)' : i === 1 ? 'rgba(12,14,34,0.9)' : 'rgba(17,19,44,0.85)';
        ctx.fill();
        if (i === 2) {
          ctx.save();
          ctx.strokeStyle = 'rgba(255,46,77,0.28)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
          ctx.stroke();
          ctx.restore();
        }
      });
    }

    function drawTorii() {
      const x = W * (W < 820 ? 0.2 : 0.58), y = H * (W < 820 ? 0.6 : 0.64), s = Math.min(W, H) * 0.072;
      ctx.save();
      ctx.strokeStyle = 'rgba(255,46,77,0.75)';
      ctx.lineWidth = Math.max(1.4, s * 0.16);
      ctx.lineCap = 'round';
      ctx.shadowColor = 'rgba(255,46,77,0.8)';
      ctx.shadowBlur = 14;
      ctx.beginPath();
      ctx.moveTo(x - s, y - s * 0.62);
      ctx.quadraticCurveTo(x, y - s * 0.9, x + s, y - s * 0.62);
      ctx.moveTo(x - s * 0.86, y - s * 0.34);
      ctx.lineTo(x + s * 0.86, y - s * 0.34);
      ctx.moveTo(x - s * 0.62, y - s * 0.34);
      ctx.lineTo(x - s * 0.66, y + s);
      ctx.moveTo(x + s * 0.62, y - s * 0.34);
      ctx.lineTo(x + s * 0.66, y + s);
      ctx.stroke();
      ctx.restore();
    }

    /* distant touge + drifting coupe */
    function drawTouge(t) {
      const horizon = H * 0.715;
      const lane = H * 0.9;
      ctx.save();

      const roadG = ctx.createLinearGradient(0, horizon, 0, lane + 40);
      roadG.addColorStop(0, 'rgba(20,22,44,0.0)');
      roadG.addColorStop(0.3, 'rgba(26,29,54,0.85)');
      roadG.addColorStop(0.7, 'rgba(16,18,36,0.95)');
      roadG.addColorStop(1, 'rgba(9,10,22,0.98)');
      ctx.fillStyle = roadG;
      ctx.beginPath();
      ctx.moveTo(W * 0.34, horizon);
      ctx.lineTo(W * 0.62, horizon);
      ctx.quadraticCurveTo(W * 0.92, lane - 26, W * 1.04, lane + 34);
      ctx.lineTo(W * 0.0, lane + 34);
      ctx.quadraticCurveTo(W * 0.18, lane - 46, W * 0.34, horizon);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = 'rgba(150,170,230,0.22)';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(W * 0.34, horizon);
      ctx.quadraticCurveTo(W * 0.18, lane - 46, 0, lane + 34);
      ctx.moveTo(W * 0.62, horizon);
      ctx.quadraticCurveTo(W * 0.92, lane - 26, W * 1.04, lane + 34);
      ctx.stroke();

      ctx.strokeStyle = 'rgba(255,46,77,0.42)';
      ctx.lineWidth = 2.2;
      ctx.setLineDash([22, 26]);
      ctx.lineDashOffset = -t * 0.13;
      ctx.beginPath();
      ctx.moveTo(W * 0.48, horizon + 4);
      ctx.quadraticCurveTo(W * 0.58, lane - 30, W * 0.7, lane + 26);
      ctx.stroke();
      ctx.setLineDash([]);

      for (let i = 0; i < 22; i++) {
        const p = i / 22;
        const py = lerp(horizon + 2, lane + 30, p * p);
        const lx = lerp(W * 0.34, -W * 0.02, p);
        const rx = lerp(W * 0.62, W * 1.06, p);
        ctx.fillStyle = `rgba(255,220,230,${0.08 + p * 0.3})`;
        ctx.fillRect(lx - 1, py, 2, 2 + p * 5);
        ctx.fillRect(rx - 1, py, 2, 2 + p * 5);
      }

      ctx.strokeStyle = 'rgba(255,255,255,0.05)';
      ctx.lineWidth = 1.6;
      [[-0.06, 0.12], [0.1, 0.3], [-0.18, 0.46]].forEach(([dx, off]) => {
        ctx.beginPath();
        const y0 = lerp(horizon + 10, lane + 20, off);
        ctx.moveTo(W * (0.5 + dx), y0);
        ctx.quadraticCurveTo(W * (0.44 + dx), y0 + 18, W * (0.34 + dx), y0 + 30);
        ctx.stroke();
      });
      ctx.restore();
    }

    function drawCar(t, energy) {
      const cx = W * (0.5 + Math.sin(t * 0.00035) * 0.16);
      const cy = H * 0.855 + Math.sin(t * 0.0011) * 2;
      const s = clamp(Math.min(W, H) * 0.0021, 0.8, 2.1);
      const slide = Math.sin(t * 0.0022) * 0.09 + energy * 0.05;

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(slide);
      ctx.scale(s, s);

      const glow = ctx.createRadialGradient(0, 18, 2, 0, 18, 96);
      glow.addColorStop(0, rgba(state.accent, 0.55));
      glow.addColorStop(0.55, rgba(state.accent, 0.16));
      glow.addColorStop(1, 'transparent');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.ellipse(0, 20, 96, 30, 0, 0, 6.2832);
      ctx.fill();

      ctx.fillStyle = '#08090f';
      [-34, 34].forEach((wx) => {
        ctx.beginPath();
        ctx.arc(wx, 6, 15, 0, 6.2832);
        ctx.fill();
      });
      ctx.strokeStyle = rgba('#c9d3ff', 0.35);
      ctx.lineWidth = 2;
      [-34, 34].forEach((wx) => {
        ctx.beginPath();
        ctx.arc(wx, 6, 15, 0, 6.2832);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(wx, 6, 5.5, 0, 6.2832);
        ctx.stroke();
      });

      const body = new Path2D();
      body.moveTo(-58, 4);
      body.bezierCurveTo(-56, -6, -44, -8, -30, -9);
      body.bezierCurveTo(-20, -24, 0, -27, 16, -24);
      body.bezierCurveTo(30, -21, 42, -13, 50, -7);
      body.bezierCurveTo(60, -6, 66, -2, 62, 7);
      body.lineTo(56, 14);
      body.lineTo(-54, 14);
      body.closePath();
      const bg = ctx.createLinearGradient(0, -26, 0, 16);
      bg.addColorStop(0, '#232a44');
      bg.addColorStop(0.45, '#131728');
      bg.addColorStop(1, '#07080f');
      ctx.fillStyle = bg;
      ctx.fill(body);
      ctx.strokeStyle = rgba('#dfe6ff', 0.28);
      ctx.lineWidth = 1.4;
      ctx.stroke(body);

      ctx.fillStyle = 'rgba(120,190,255,0.18)';
      ctx.beginPath();
      ctx.moveTo(-16, -22);
      ctx.lineTo(12, -22);
      ctx.lineTo(22, -12);
      ctx.lineTo(-22, -12);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = '#0a0a12';
      ctx.beginPath();
      ctx.moveTo(-52, -12);
      ctx.lineTo(-30, -18);
      ctx.lineTo(-30, -10);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = rgba('#ff2e4d', 0.85);
      ctx.fillRect(-60, -4, 7, 5);
      ctx.shadowColor = '#ff2e4d';
      ctx.shadowBlur = 12;
      ctx.fillRect(-60, -4, 7, 5);
      ctx.shadowBlur = 0;

      ctx.fillStyle = '#12141f';
      ctx.fillRect(52, -6, 12, 3);
      ctx.fillRect(56, -14, 3, 9);

      ctx.restore();

      /* tyre smoke */
      smokeTimer -= 1;
      const rate = 2 + Math.round(energy * 14);
      if (smokeTimer <= 0) {
        smokeTimer = Math.max(1, 9 - Math.round(energy * 6));
        for (let i = 0; i < rate; i++) {
          smokes.push({
            x: cx - 34 * s * clamp(s, 0.7, 1.5),
            y: cy + 8 * clamp(s, 0.7, 1.5),
            vx: -0.9 - Math.random() * 1.6,
            vy: -0.25 - Math.random() * 0.8,
            r: 5 + Math.random() * 9,
            a: 0.24 + Math.random() * 0.2,
            life: 1,
          });
        }
      }
      for (let i = smokes.length - 1; i >= 0; i--) {
        const p = smokes[i];
        p.x += p.vx;
        p.y += p.vy;
        p.r += 0.32;
        p.life -= 0.0075;
        if (p.life <= 0) { smokes.splice(i, 1); continue; }
        ctx.fillStyle = `rgba(214,222,255,${p.a * p.life * 0.5})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, 6.2832);
        ctx.fill();
      }

      if (energy > 0.22) {
        ctx.strokeStyle = rgba('#ffffff', 0.06 + energy * 0.14);
        ctx.lineWidth = 1;
        for (let i = 0; i < 9; i++) {
          const y = cy - 26 + Math.random() * 46;
          const len = 40 + Math.random() * 160 * energy;
          ctx.beginPath();
          ctx.moveTo(cx - len, y);
          ctx.lineTo(cx - len * 0.35, y);
          ctx.stroke();
        }
      }
    }

    function drawPetals(t) {
      for (const p of petals) {
        p.x += p.vx + Math.sin(t * 0.0006 + p.rot) * 0.3;
        p.y += p.vy;
        p.rot += p.vr;
        if (p.y > H + 20) { p.y = -20; p.x = Math.random() * W; }
        if (p.x > W + 20) p.x = -20;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.globalAlpha = p.a;
        ctx.fillStyle = '#ff9ecb';
        ctx.beginPath();
        ctx.ellipse(0, 0, p.s, p.s * 0.45, 0, 0, 6.2832);
        ctx.fill();
        ctx.restore();
      }
      ctx.globalAlpha = 1;
    }

    function drawFog() {
      const g = ctx.createLinearGradient(0, H * 0.72, 0, H);
      g.addColorStop(0, 'transparent');
      g.addColorStop(0.6, 'rgba(255,120,160,0.05)');
      g.addColorStop(1, 'rgba(5,6,14,0.9)');
      ctx.fillStyle = g;
      ctx.fillRect(0, H * 0.72, W, H * 0.28);
    }

    function frame(t) {
      drawSky(t);
      drawMoon(t);
      drawClouds(t);
      drawHills();
      drawTorii();
      drawTouge(t);
      drawCar(t, state.energy);
      drawPetals(t);
      drawFog();
      requestAnimationFrame(frame);
    }

    function start() {
      resize();
      window.addEventListener('resize', () => { resize(); });
      requestAnimationFrame(frame);
    }
    return { start, get size() { return { W, H }; } };
  })();

  /* ======================================================== tachometer */
  const Tach = (() => {
    const CX = 210, CY = 208, R = 152;
    const START = 135, SWEEP = 270;   // screen-clockwise, from lower-left to lower-right
    let cur = 0, target = 0, shown = 0;

    const CID = (n) => n.toFixed(2);
    const pt = (ang, r) => [CX + Math.cos((ang * Math.PI) / 180) * r,
                            CY + Math.sin((ang * Math.PI) / 180) * r];

    function build() {
      let html = '';
      for (let i = 0; i <= 20; i++) {
        const frac = i / 20;
        const ang = START + SWEEP * frac;
        const major = i % 2 === 0;
        const red = frac >= 0.85;
        const [x1, y1] = pt(ang, R - (major ? 20 : 11));
        const [x2, y2] = pt(ang, R);
        html += `<line class="tick ${major ? 'major' : ''} ${red ? 'red' : ''}" x1="${CID(x1)}" y1="${CID(y1)}" x2="${CID(x2)}" y2="${CID(y2)}"/>`;
      }
      $('tach-ticks').innerHTML = html;
      const [ax, ay] = pt(START + SWEEP * 0.85, R + 11);
      const [bx, by] = pt(START + SWEEP, R + 11);
      $('tach-redline').setAttribute('d', `M ${CID(ax)} ${CID(ay)} A ${R + 11} ${R + 11} 0 0 1 ${CID(bx)} ${CID(by)}`);
    }

    function update(progress, jitter) {
      target = clamp(progress, 0, 1);
      cur = lerp(cur, target, 0.075);
      shown = lerp(shown, START + SWEEP * cur, 0.18);
      $('tach-needle').style.transform = `rotate(${(shown + (jitter || 0) - 270).toFixed(2)}deg)`;
    }
    function setGear(g) { $('gear').textContent = g; }
    return { build, update, setGear };
  })();

  /* ==================================================== danmaku analyser */
  const Viz = (() => {
    const canvas = $('viz');
    const ctx = canvas.getContext('2d');
    let W = 0, H = 0, dpr = 1, orbit = 0;

    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = canvas.clientWidth || 260;
      H = canvas.clientHeight || 118;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function frame(t) {
      ctx.clearRect(0, 0, W, H);
      const spec = state.spectrum;
      const n = 40;
      const mid = H / 2;
      const accent = state.accent;

      ctx.save();
      ctx.translate(W / 2, mid);
      ctx.rotate(orbit);
      ctx.strokeStyle = rgba(accent, 0.22);
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 7]);
      const rr = Math.max(18, Math.min(W * 0.32, H * 0.44));
      ctx.beginPath();
      ctx.ellipse(0, 0, rr, rr * 0.62, 0, 0, 6.2832);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
      orbit += (0.0016 + state.energy * 0.006);

      const w = W / n;
      for (let i = 0; i < n; i++) {
        const v = spec[Math.floor((i / n) * spec.length)] || 0;
        const h = clamp(v * H * 0.44, 1.2, H * 0.46);
        const x = i * w + 1.6;
        const hueMix = mixHex('#4fe3ff', accent, i / n);
        const grad = ctx.createLinearGradient(0, mid - h, 0, mid + h);
        grad.addColorStop(0, rgba(hueMix, 0.18));
        grad.addColorStop(0.5, rgba(hueMix, 0.95));
        grad.addColorStop(1, rgba(hueMix, 0.18));
        ctx.fillStyle = grad;
        ctx.fillRect(x, mid - h, Math.max(1.4, w - 3.2), h * 2);

        if (v > 0.34) {
          const rr2 = 1.6 + v * 4.4;
          ctx.fillStyle = rgba('#fff6fb', 0.85);
          ctx.shadowColor = hueMix;
          ctx.shadowBlur = 10;
          ctx.beginPath();
          ctx.arc(x + w * 0.42, mid - h - rr2 - 1, rr2, 0, 6.2832);
          ctx.fill();
          ctx.beginPath();
          ctx.arc(x + w * 0.42, mid + h + rr2 + 1, rr2, 0, 6.2832);
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }

      ctx.strokeStyle = rgba('#ffffff', 0.14);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, mid);
      ctx.lineTo(W, mid);
      ctx.stroke();
    }
    return { resize, frame };
  })();

  /* ============================================================ audio */
  const Audio_ = (() => {
    const el = $('audio');
    let actx = null, analyser = null, detAnalyser = null, data = null, detData = null;
    let srcNode = null, failed = false;

    function connect() {
      try {
        if (!actx) {
          actx = new (window.AudioContext || window.webkitAudioContext)();
          analyser = actx.createAnalyser();
          analyser.fftSize = 512;
          analyser.smoothingTimeConstant = 0.72;
          data = new Uint8Array(analyser.frequencyBinCount);
          detAnalyser = actx.createAnalyser();
          detAnalyser.fftSize = 4096;
          detAnalyser.smoothingTimeConstant = 0;
          detAnalyser.minDecibels = -100;
          detAnalyser.maxDecibels = -20;
          detData = new Uint8Array(detAnalyser.frequencyBinCount);
          srcNode = actx.createMediaElementSource(el);
          srcNode.connect(analyser);
          srcNode.connect(detAnalyser);
          analyser.connect(actx.destination);
        }
        if (actx.state === 'suspended') actx.resume();
        return true;
      } catch (err) {
        failed = true;
        return false;
      }
    }

    function sample() {
      const spec = state.spectrum;
      if (analyser && data && !failed) {
        analyser.getByteFrequencyData(data);
        const bins = 64;
        let energy = 0, bass = 0;
        for (let i = 0; i < bins; i++) {
          const idx = Math.floor(Math.pow(i / bins, 1.35) * (data.length * 0.72));
          const v = data[idx] / 255;
          spec[i] = lerp(spec[i], v, 0.32);
          energy += v;
          if (i < 12) bass += v;
        }
        state.energy = clamp(energy / bins * 1.9, 0, 1);
        state.bass = clamp(bass / 12 * 1.4, 0, 1);
      } else {
        const t = performance.now() * 0.001;
        for (let i = 0; i < spec.length; i++) {
          const v = state.playing
            ? clamp(0.18 + 0.5 * Math.abs(Math.sin(t * 1.7 + i * 0.42)) * Math.abs(Math.sin(t * 0.33 + i * 0.07)) + 0.22 * Math.abs(Math.sin(t * 4.1 + i)), 0, 1)
            : 0.02 + 0.02 * Math.abs(Math.sin(t + i));
          spec[i] = lerp(spec[i], v, 0.25);
        }
        state.energy = lerp(state.energy, state.playing ? 0.4 + 0.3 * Math.abs(Math.sin(t * 2.3)) : 0.03, 0.1);
        state.bass = state.energy;
      }
    }

    function bufferedLag() {
      try {
        if (!el.buffered || !el.buffered.length) return 0;
        const end = el.buffered.end(el.buffered.length - 1);
        return clamp(end - el.currentTime, 0, 25);
      } catch (err) {
        return 0;
      }
    }

    function scheduleReconnect() {
      if (state.userPaused || !state.everPlayed) return;
      const delay = Math.min(9000, 700 * Math.pow(2, state.retries || 0));
      state.retries = (state.retries || 0) + 1;
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = setTimeout(() => {
        try {
          el.dataset.stale = '1';
          el.load();
          const p = el.play();
          if (p && p.catch) p.catch(() => {});
        } catch (err) { /* keep trying on the next event */ }
      }, delay);
    }

    function play() {
      const had = el.src && el.src.length;
      if (!had || el.dataset.stale === '1') {
        el.src = (state.stream || '/stream') + '?t=' + Date.now();
        el.dataset.stale = '0';
      }
      connect();
      const p = el.play();
      if (p && p.catch) p.catch(() => {});
      state.playing = true;
      state.userPaused = false;
      state.everPlayed = true;
      paintPlayButton();
    }
    function pause() {
      state.userPaused = true;
      el.pause();
      state.playing = false;
      paintPlayButton();
    }
    function toggle() { state.playing ? pause() : play(); }

    function paintPaused() {
      state.playing = false;
      paintPlayButton();
    }

    function paintPlayButton() {
      const btn = $('play');
      btn.classList.toggle('playing', state.playing);
      $('play-icon').textContent = state.playing ? '❚❚' : '▶';
      $('play-label').textContent = state.playing ? t('live') : t('ignition');
    }

    function paintVolume(value) {
      const v = clamp(Number(value) || 0, 0, 100);
      $('vol').style.setProperty('--fill', v + '%');
      $('vol-val').textContent = String(Math.round(v));
      el.volume = v / 100;
    }

    function init() {
      paintVolume($('vol').value || 80);
      el.addEventListener('playing', () => {
        state.playing = true;
        state.everPlayed = true;
        state.retries = 0;
        paintPlayButton();
        if (!state.calibrated || Date.now() - (state.lastPauseAt || 0) > 4000) calibrate();
      });
      el.addEventListener('pause', () => { state.playing = false; state.lastPauseAt = Date.now(); paintPlayButton(); });
      el.addEventListener('error', () => {
        el.dataset.stale = '1';
        state.playing = false;
        paintPlayButton();
        scheduleReconnect();
      });
      el.addEventListener('ended', scheduleReconnect);
      el.addEventListener('stalled', () => {
        el.dataset.stale = '1';
        scheduleReconnect();
      });
      $('play').addEventListener('click', toggle);
      $('vol').addEventListener('input', (e) => paintVolume(e.target.value));
      $('dj-replay').addEventListener('click', () => {
        const src = (state.now && state.now.dj_clip) || '/api/dj/current.wav';
        const a = new Audio(src + '?t=' + Date.now());
        a.volume = el.volume;
        a.play().catch(() => {});
        const btn = $('dj-replay');
        btn.style.color = '#4fe3ff';
        setTimeout(() => { btn.style.color = ''; }, 1400);
      });
      window.addEventListener('keydown', (e) => {
        if (e.code === 'Space' && !/input|textarea/i.test(e.target.tagName)) { e.preventDefault(); toggle(); }
        if (e.key === 'm') { el.muted = !el.muted; }
      });
      setInterval(() => {
        if (!state.userPaused && state.everPlayed && (el.paused || el.networkState === 3)) {
          if (el.networkState === 3 || el.ended || !el.src) scheduleReconnect();
        }
      }, 2500);
    }
    const detector = () => (detAnalyser ? { analyser: detAnalyser, data: detData } : null);
    return { init, sample, play, pause, toggle, paintPaused, bufferedLag, detector };
  })();

  /* ====================================================== audio sync
     A 16 kHz three-pulse marker is mixed into every track and can be injected
     on demand. Detecting it tells us exactly when the audio we HEAR reached a
     known point, so the progress bar stops guessing at buffer latency.        */
  const Sync = (() => {
    const FREQ = 16000, FFT = 4096;
    let BIN = 0;                       // resolved from the real AudioContext rate
    const MIN_ABS = 135, DELTA = 18, CLUSTER_GAP = 420, PULSE_SPLIT = 110;
    let pulses = [], lastAt = 0, lastFire = 0, handler = null;
    const stats = { peak: 0, ref: 0, markers: 0, hits: 0, lag: null };

    function scan() {
      const det = Audio_.detector();
      if (!det || !state.playing) return;
      det.analyser.getByteFrequencyData(det.data);
      const arr = det.data;
      if (!BIN) BIN = Math.round(FREQ / (det.analyser.context.sampleRate / FFT));
      let peak = 0;
      for (let b = BIN - 2; b <= BIN + 2; b++) peak = Math.max(peak, arr[b] || 0);
      let ref = 0;
      for (let b = BIN - 20; b <= BIN - 9; b++) ref = Math.max(ref, arr[b] || 0);
      for (let b = BIN + 9; b <= BIN + 20; b++) ref = Math.max(ref, arr[b] || 0);
      stats.peak = peak;
      stats.ref = ref;
      const t = performance.now();
      const hit = peak >= MIN_ABS && peak >= ref + DELTA;
      if (hit) {
        stats.hits += 1;
        if (t - lastAt > CLUSTER_GAP) {
          if (pulses.length >= 3) fire(pulses[0]);
          pulses = [];
        }
        if (!pulses.length || t - lastAt > PULSE_SPLIT) pulses.push(t);
        lastAt = t;
      } else if (pulses.length && t - lastAt > CLUSTER_GAP) {
        if (pulses.length >= 3) fire(pulses[0]);
        pulses = [];
      }
    }

    function fire(t) {
      if (t - lastFire < 700) return;
      lastFire = t;
      stats.markers += 1;
      if (handler) handler(t);
    }

    return {
      scan,
      stats,
      set onMarker(fn) { handler = fn; },
      get bin() { return BIN; },
      get rate() { return (Audio_.detector() || {}).analyser ? Audio_.detector().analyser.context.sampleRate : 0; },
    };
  })();

  /* ====================================================== station data */
  function setAccent(hex) {
    state.accent = hex || '#ff5c8a';
    document.documentElement.style.setProperty('--accent', state.accent);
    document.documentElement.style.setProperty('--accent-soft', rgba(state.accent, 0.18));
  }

  function renderCharacter(char) {
    if (!char || !char.spec) return;
    $('char-art').innerHTML = YoukaiArt.render(char.spec, { accent: char.color, uid: char.key });
    const cname = (ZH && char.name_zh) || char.name || '';
    const cepi = (ZH && char.epithet_zh) || char.epithet || '';
    $('char-name').textContent = cname;
    $('char-epithet').textContent = cepi + (char.jp ? ' · ' + char.jp : '');
    $('char-chip').textContent = ZH ? cname : (char.name || '').toUpperCase();
    setAccent(char.color);
  }

  function typeText(el, text) {
    state.typers.forEach((t) => clearTimeout(t));
    state.typers = [];
    el.textContent = '';
    el.classList.add('typing');
    let i = 0;
    const step = () => {
      if (i >= text.length) { el.classList.remove('typing'); return; }
      el.textContent = text.slice(0, ++i);
      state.typers.push(setTimeout(step, 12 + Math.random() * 15));
    };
    step();
  }

  function listItems(entries, currentTitle) {
    if (!entries || !entries.length) return '<li class="muted">waiting for the next lap…</li>';
    return entries.map((e, i) => {
      const cur = currentTitle && e.title === currentTitle ? ' current' : '';
      const color = e.color || (state.station && state.station.characters[e.character_key] || {}).color || '#ff5c8a';
      return `<li class="${cur}" style="border-left-color:${cur ? color : 'transparent'}">
        <span class="idx">${String(i + 1).padStart(2, '0')}</span>
        <span class="t" title="${(e.title || '').replace(/"/g, '&quot;')}">${e.title || ''}</span>
        <span class="a" style="color:${color}">${(e.artist || '').slice(0, 14)}</span>
      </li>`;
    }).join('');
  }

  function renderStation(s) {
    state.station = s;
    state.stream = s.stream;
    if (s.dj) {
      $('dj-name').textContent = s.dj.name;
      $('dj-role').textContent = (s.dj.name_jp || '') + ' · ' + t('djrole');
    }
    const bits = ZH ? [
      '<b>◇</b> ' + s.station_jp + ' ' + s.station,
      '<b>◇</b> TOUHOU EUROBEAT 全天候放送',
      '<b>◇</b> 东方 EUROBEAT · ' + s.tagline,
      '<b>◇</b> 曲库 ' + s.track_count + ' 首',
      '<b>◇</b> 夜雀 ' + s.dj.name + ' 在麦克风前',
      '<b>◇</b> 午夜山道漂移 · ' + s.location,
    ] : [
      '<b>◇</b> ' + s.station_jp + ' ' + s.station,
      '<b>◇</b> TOUHOU EUROBEAT 24/7',
      '<b>◇</b> ' + s.tagline,
      '<b>◇</b> LIBRARY ' + s.track_count + ' TRACKS',
      '<b>◇</b> ' + s.dj.name + ' ON THE MIC',
      '<b>◇</b> MIDNIGHT TOUGE · ' + s.location,
    ];
    $('ticker-run').innerHTML = (bits.join(' ') + ' ').repeat(4);
  }

  function renderNow(data) {
    const now = data.now || {};
    state.now = now;
    const key = (now.title || '') + '|' + (now.started_at || '');
    if (key !== state.lastKey) {
      state.lastKey = key;
      state.sync = null;
      if (now.character) renderCharacter(now.character);
      const title = $('track-title');
      title.textContent = now.title || '—';
      title.classList.remove('glitch');
      void title.offsetWidth;
      title.classList.add('glitch');
      $('track-artist').textContent = (now.artist || 'Midnight Youkai Radio').toUpperCase();
      $('track-album').textContent = (now.album || (now.kind === 'bed' ? 'INTERLUDE' : '')).toUpperCase();
      typeText($('dj-text'), now.dj_text || t('quiet'));
      const replay = $('dj-replay');
      const hasClip = !!(now.dj_clip && now.dj_text);
      replay.disabled = !hasClip;
      replay.classList.toggle('off', !hasClip);
      replay.querySelector('span').textContent = hasClip ? t('replay') : t('novoice');
      const lbl = (ZH && now.character && now.character.epithet_zh)
        || (now.character && now.character.epithet) || 'EUROBEAT';
      $('gauge-label').textContent = ZH ? lbl.slice(0, 14) : lbl.toUpperCase().slice(0, 22);
    }
    state.progress = data.progress || state.progress;
    state.online = !!data.online;
    $('listeners').textContent = data.listeners != null ? data.listeners : '–';
    const live = $('live');
    live.classList.toggle('off', !state.online);
    $('live-label').textContent = state.online ? t('live') : t('offline');
    $('viz-state').textContent = state.playing ? t('locked') : t('idle');
    const eng = data.engine || {};
    $('queue-list').innerHTML = listItems((eng.upcoming || []).slice(0, 6), eng.current);
    $('history-list').innerHTML = listItems((data.history || []).slice(0, 12), now.title);
  }

  function heardPosition(fallbackLag) {
    const dur = state.progress.duration || 0;
    let v;
    if (state.sync && state.sync.key === state.lastKey) {
      v = state.sync.base + (performance.now() - state.sync.at) / 1000;
    } else {
      const lag = state.measuredLag != null ? state.measuredLag : fallbackLag + PIPELINE_LAG_S;
      v = state.progress.elapsed - lag;
    }
    v = Math.max(0, v);
    return dur ? Math.min(v, dur) : v;
  }

  function onMarkerHeard(t) {
    const epoch = Date.now();
    state.lastMarkerEpoch = epoch;
    const calib = state.calib;
    if (calib && calib.injectedAt && !calib.done) {
      const lag = epoch / 1000 - calib.injectedAt;
      if (lag > 0.15 && lag < 20) {
        state.measuredLag = lag;
        calib.done = true;
        Sync.stats.lag = +lag.toFixed(2);
      }
      return;
    }
    const now = state.now || {};
    if (!now.started_at) return;
    const lag = epoch / 1000 - now.started_at - 0.06;
    if (lag <= 0.3 || lag > 25) return;
    if (state.measuredLag != null && Math.abs(lag - state.measuredLag) > 2.5) return;
    state.sync = { key: state.lastKey, at: t, base: 0.06 };
    state.measuredLag = lag;
    Sync.stats.lag = +lag.toFixed(2);
  }

  async function calibrate() {
    state.calibrated = true;
    const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
    state.calib = { nonce, injectedAt: null, done: false };
    try {
      const res = await fetch(api('/api/calibrate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nonce: nonce, lang: LANG }),
      });
      const head = await res.json();
      if (head && head.server_time != null) state.clockOffset = head.server_time;
      for (let i = 0; i < 14; i++) {
        await new Promise((r) => setTimeout(r, 600));
        const q = await fetch(api('/api/calibrate/' + nonce), { cache: 'no-store' });
        if (q.status === 200) {
          const j = await q.json();
          state.calib.injectedAt = j.injected_at;
          if (state.lastMarkerEpoch > j.injected_at * 1000 && !state.calib.done) {
            const lag = state.lastMarkerEpoch / 1000 - j.injected_at;
            if (lag > -0.5 && lag < 30) {
              state.measuredLag = lag;
              state.calib.done = true;
              Sync.stats.lag = +lag.toFixed(2);
            }
          }
          if (state.calib.done) return;
        }
      }
    } catch (err) {
      /* calibration is best-effort: the buffered-lag fallback stays in place */
    }
  }

  function renderClock() {
    const d = new Date();
    $('clock').textContent = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    const off = -d.getTimezoneOffset() / 60;
    $('clock-zone').textContent = 'UTC' + (off >= 0 ? '+' : '') + off;
  }

  async function poll() {
    try {
      const data = await fetchJSON(api('/api/now-playing'));
      renderNow(data);
    } catch (err) {
      $('live').classList.add('off');
      $('live-label').textContent = t('offline');
    }
  }

  /* ============================================================= main */
  function boot() {
    applyI18n();
    setAccent('#ff5c8a');
    Tach.build();
    Scene.start();
    Viz.resize();
    Audio_.init();
    window.addEventListener('resize', Viz.resize);
    renderClock();
    setInterval(renderClock, 10000);

    fetchJSON(api('/api/station')).then(renderStation).catch(() => {});
    poll();
    setInterval(poll, 3000);

    let last = performance.now();
    let shownLag = 0;
    function loop(t) {
      const dt = t - last;
      last = t;
      Audio_.sample();
      shownLag = lerp(shownLag, Audio_.bufferedLag(), 0.06);
      state.progress.elapsed += (state.playing ? dt : 0) / 1000;
      Sync.scan();
      const heard = heardPosition(shownLag);
      const prog = state.progress.duration ? heard / state.progress.duration : 0;
      Tach.update(prog, Math.sin(t * 0.009) * state.energy * 3.2);
      Tach.setGear(String(clamp(1 + Math.floor(prog * 6), 1, 6)));
      $('elapsed').textContent = fmtTime(heard);
      $('total').textContent = fmtTime(state.progress.duration);
      $('viz-bpm').textContent = (I18N[LANG] || I18N.en).energy + ' ' + String(Math.round(state.energy * 100)).padStart(3, '0');
      Viz.frame(t);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);

    Audio_.paintPaused();
    Sync.onMarker = onMarkerHeard;
    window.__myr = { state, Sync, audio: Audio_, heardPosition };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
