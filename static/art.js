/* Midnight Youkai Radio — parametric youkai silhouette art.
   Back-view, backlit poster style: near-black garments, coloured rim light,
   accent-tinted gradient so the figure reads against the night sky.
   Driven entirely by the character spec served from /api/station. */

const YoukaiArt = (() => {
  /* fill tokens resolved per character */
  const TOK = { body: '@body', dark: '@dark', hair: '@hair', hairHi: '@hairHi', trim: '@trim', cloth: '@cloth' };

  function hexToRgb(hex) {
    const h = String(hex || '#ff5c8a').replace('#', '');
    const v = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
  }
  function rgbToHex([r, g, b]) {
    return '#' + [r, g, b].map((n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0')).join('');
  }
  const mix = (a, b, t) => {
    const A = hexToRgb(a), B = hexToRgb(b);
    return rgbToHex([A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t]);
  };
  const intoNight = (c, t) => mix(c, '#070a16', t);

  /* ---------------------------------------------------------------- hair */
  function hair(style, c, tie, layer) {
    const dark = intoNight(c, 0.62);
    const hi = mix(c, '#ffffff', 0.22);
    const out = [];
    const shell = 'M160 84 C108 84 96 124 99 164 C104 122 126 106 160 106 C194 106 216 122 221 164 C224 124 212 84 160 84 Z';
    const cap = 'M160 86 C112 86 100 122 102 158 C108 120 130 108 160 108 C190 108 212 120 218 158 C220 122 208 86 160 86 Z';
    if (layer === 'behind') {
      if (style === 'long') {
        out.push(['M102 158 Q86 300 96 436 Q128 458 160 452 Q192 458 224 436 Q234 300 218 158 Z', TOK.hair]);
        out.push(['M104 150 Q92 252 104 336 Q122 332 118 250 Q116 190 124 156 Z', dark]);
        out.push(['M216 150 Q228 252 216 336 Q198 332 202 250 Q204 190 196 156 Z', dark]);
      } else if (style === 'twintail') {
        out.push(['M114 138 Q74 152 66 226 Q58 310 84 384 Q104 398 118 364 Q96 292 104 222 Q108 176 132 158 Z', TOK.hair]);
        out.push(['M206 138 Q246 152 254 226 Q262 310 236 384 Q216 398 202 364 Q224 292 216 222 Q212 176 188 158 Z', TOK.hair]);
      } else if (style === 'side_ponytail') {
        out.push(['M214 142 Q262 158 266 242 Q268 322 238 394 Q216 408 204 372 Q228 300 220 232 Q216 180 196 158 Z', TOK.hair]);
      } else if (style === 'braid') {
        for (let i = 0; i < 4; i++) {
          const y = 296 + i * 46, w = 31 - i * 2.5, x = 222 - i * 4;
          out.push([`M${x} ${y} Q${x + w} ${y + 23} ${x} ${y + 46} Q${x - w} ${y + 23} ${x} ${y} Z`, dark]);
        }
      } else if (style === 'bun') {
        out.push(['M160 44 m-32 0 a32 28 0 1 0 64 0 a32 28 0 1 0 -64 0', dark]);
      } else {
        out.push(['M104 156 Q96 216 120 240 Q132 208 122 168 Z', dark]);
        out.push(['M216 156 Q224 216 200 240 Q188 208 198 168 Z', dark]);
      }
      out.push([shell, TOK.hair]);
    } else {
      out.push([cap, TOK.hair]);
      out.push(['M112 96 Q136 84 160 84 Q132 92 112 108 Z', hi]);
      if (['short', 'side_ponytail', 'braid'].includes(style)) {
        out.push(['M104 156 Q100 196 112 224 Q126 208 120 170 Z', hi]);
        out.push(['M216 156 Q220 196 208 224 Q194 208 200 170 Z', hi]);
      }
      if (style === 'twintail') {
        out.push(['M118 150 Q104 160 102 178 Q118 182 128 166 Z', TOK.trim]);
        out.push(['M202 150 Q216 160 218 178 Q202 182 192 166 Z', TOK.trim]);
      }
      if (style === 'side_ponytail' || style === 'braid') {
        out.push(['M206 152 Q224 156 226 174 Q208 178 198 162 Z', TOK.trim]);
      }
      if (style === 'long' || style === 'twintail') {
        out.push(['M104 146 Q96 170 104 190 Q118 180 116 150 Z', TOK.trim]);
        out.push(['M216 146 Q224 170 216 190 Q202 180 204 150 Z', TOK.trim]);
      }
    }
    return out;
  }

  /* ------------------------------------------------------------- headwear */
  function headwear(type, c) {
    const light = intoNight(c, 0.2);
    const dark = intoNight(c, 0.5);
    switch (type) {
      case 'bow':
        return [
          ['M160 78 L102 44 Q86 76 106 102 Z', TOK.trim],
          ['M160 78 L218 44 Q234 76 214 102 Z', TOK.trim],
          ['M160 80 m-12 0 a12 12 0 1 0 24 0 a12 12 0 1 0 -24 0', dark],
        ];
      case 'ribbon':
        return [
          ['M198 78 L172 56 Q160 78 176 94 Z', TOK.trim],
          ['M198 78 L226 58 Q236 78 216 94 Z', TOK.trim],
          ['M198 80 m-10 0 a10 10 0 1 0 20 0 a10 10 0 1 0 -20 0', dark],
          ['M190 90 L176 132 L192 126 Z', TOK.trim],
        ];
      case 'witch_hat':
        return [
          ['M160 2 L212 100 L108 100 Z', dark],
          ['M160 2 L186 100 L134 100 Z', light],
          ['M160 102 m-100 0 a100 23 0 1 0 200 0 a100 23 0 1 0 -200 0', dark],
          ['M112 84 L208 84 L212 100 L108 100 Z', TOK.trim],
        ];
      case 'mob_cap':
        return [
          ['M104 126 Q160 80 216 126 Q160 142 104 126 Z', light],
          ...[0, 1, 2, 3, 4].map((i) => `M${110 + i * 25} 124 m-12 0 a12 13 0 1 0 24 0 a12 13 0 1 0 -24 0`).map((d) => [d, light]),
        ];
      case 'nightcap':
        return [
          ['M124 118 Q160 92 198 118 Q198 60 176 28 Q160 8 144 26 Q126 50 140 74 Q130 98 124 118 Z', light],
          ['M140 24 m-15 0 a15 15 0 1 0 30 0 a15 15 0 1 0 -30 0', TOK.trim],
        ];
      case 'headband':
        return [['M98 124 Q160 98 222 124 L222 138 Q160 112 98 138 Z', light]];
      case 'tokin':
        return [
          ['M132 98 L188 98 L188 56 L132 56 Z', light],
          ['M132 56 m-28 0 a28 13 0 1 0 56 0 a28 13 0 1 0 -56 0', light],
          ['M160 44 m-12 0 a12 12 0 1 0 24 0 a12 12 0 1 0 -24 0', TOK.trim],
        ];
      case 'hat':
        return [
          ['M160 114 m-100 0 a100 25 0 1 0 200 0 a100 25 0 1 0 -200 0', dark],
          ['M104 114 Q160 46 216 114 Q160 96 104 114 Z', light],
          ['M102 104 L218 104 L220 116 L100 116 Z', TOK.trim],
        ];
      case 'ears':
        return [
          ['M134 98 Q114 26 130 10 Q150 24 148 98 Z', light],
          ['M186 98 Q206 26 190 10 Q170 24 172 98 Z', light],
        ];
      default:
        return [];
    }
  }

  /* ---------------------------------------------------------- accessories */
  function accessory(type, c, layer) {
    const dark = intoNight(c, 0.45);
    const light = intoNight(c, 0.12);
    const w = (shapes) => (layer === 'behind' ? shapes : []);
    switch (type) {
      case 'bat_wings':
        return w([
          ['M108 212 Q46 168 10 226 Q32 232 24 256 Q52 248 58 268 Q78 252 88 266 Q94 240 108 244 Z', TOK.dark],
          ['M212 212 Q274 168 310 226 Q288 232 296 256 Q268 248 262 268 Q242 252 232 266 Q226 240 212 244 Z', TOK.dark],
        ]);
      case 'crystal_wings':
        return w([
          ['M112 214 L40 144 L68 234 Z', light],
          ['M108 248 L24 214 L98 280 Z', light],
          ['M112 284 L46 302 L112 318 Z', light],
          ['M208 214 L280 144 L252 234 Z', light],
          ['M212 248 L296 214 L222 280 Z', light],
          ['M208 284 L274 302 L208 318 Z', light],
        ]);
      case 'ice_wings':
        return w([
          ['M110 220 L52 164 L72 234 Z', light],
          ['M106 258 L30 232 L100 292 Z', light],
          ['M210 220 L268 164 L248 234 Z', light],
          ['M214 258 L290 232 L220 292 Z', light],
        ]);
      case 'crow_wings':
        return w([
          ['M110 206 Q46 154 12 196 Q52 214 96 252 Z', TOK.dark],
          ['M110 240 Q42 226 22 272 Q64 272 104 286 Z', TOK.dark],
          ['M210 206 Q274 154 308 196 Q268 214 224 252 Z', TOK.dark],
          ['M210 240 Q278 226 298 272 Q256 272 216 286 Z', TOK.dark],
        ]);
      case 'moon':
        return w([['M160 146 m-108 0 a108 108 0 1 0 216 0 a108 108 0 1 0 -216 0', 'none', `stroke="${light}" stroke-width="13" opacity="0.45"`]]);
      case 'gohei':
        return [
          ['M92 324 L74 534 L86 534 L106 324 Z', TOK.dark],
          ['M74 364 L30 400 L38 420 L78 386 Z', light],
          ['M78 402 L34 446 L44 464 L84 424 Z', light],
        ];
      case 'broom':
        return [
          ['M228 296 L264 532 L276 528 L242 292 Z', TOK.dark],
          ['M254 516 L300 558 L270 586 L236 544 Z', light],
        ];
      case 'sword':
        return [
          ['M214 296 L250 456 L240 460 L204 302 Z', light],
          ['M204 300 L222 286 L228 296 L210 308 Z', TOK.dark],
          ['M238 452 L256 468 L248 476 L230 460 Z', TOK.dark],
        ];
      case 'parasol':
        return w([
          ['M28 96 Q160 0 292 96 Q160 72 28 96 Z', TOK.dark],
          ['M160 72 L160 300 L167 300 L167 72 Z', TOK.dark],
          ['M36 92 L160 72 L160 100 Z', light],
        ]);
      case 'lantern':
        return [
          ['M248 300 L248 320 M230 308 L282 308', 'none', `stroke="${light}" stroke-width="3"`],
          ['M244 320 L244 352 L284 352 L284 320 Z', TOK.dark],
          ['M249 354 L249 404 Q264 416 279 404 L279 354 Z', light],
        ];
      case 'book':
        return [
          ['M226 314 L286 296 L290 358 L230 376 Z', light],
          ['M226 314 L170 298 L166 360 L222 376 Z', TOK.dark],
        ];
      case 'knife':
        return [
          ['M70 262 L34 234 L22 250 L60 278 Z', light],
          ['M258 290 L298 262 L310 280 L268 304 Z', light],
          ['M80 332 L42 322 L36 340 L76 348 Z', light],
        ];
      case 'fire':
        return w([
          ['M96 150 Q72 114 78 86 Q100 110 108 82 Q120 120 96 150 Z', light],
          ['M228 132 Q260 94 252 62 Q224 94 216 58 Q204 102 228 132 Z', light],
          ['M160 36 Q140 12 146 -4 Q160 8 168 -4 Q176 16 160 36 Z', light],
        ]);
      case 'third_eye':
        return w([
          ['M160 62 m-32 0 a32 32 0 1 0 64 0 a32 32 0 1 0 -64 0', light],
          ['M141 64 Q160 80 179 64', 'none', 'stroke="#06070f" stroke-width="6" fill="none"'],
          ['M134 84 L118 156 M160 92 L160 158 M186 84 L202 156', 'none', `stroke="${light}" stroke-width="3"`],
        ]);
      case 'snake':
        return w([
          ['M196 104 Q234 76 258 106 Q278 134 250 150 Q228 162 238 184', 'none', `stroke="${light}" stroke-width="13" fill="none" stroke-linecap="round"`],
          ['M246 178 m-12 0 a12 12 0 1 0 24 0 a12 12 0 1 0 -24 0', light],
        ]);
      default:
        return [];
    }
  }

  /* -------------------------------------------------------------- outfits */
  function outfit(type, main, sub, acc) {
    const body = [];
    const legs = (y0) => [
      [`M140 ${y0} L136 588 Q136 602 150 602 Q163 602 162 588 L160 ${y0 + 6} Z`, TOK.dark],
      [`M180 ${y0} L182 588 Q182 602 195 602 Q208 602 208 588 L181 ${y0 + 6} Z`, TOK.dark],
    ];
    const shoes = (y) => [
      [`M134 ${y - 14} L132 ${y} L166 ${y} L162 ${y - 14} Z`, TOK.trim],
      [`M178 ${y - 14} L178 ${y} L212 ${y} L206 ${y - 14} Z`, TOK.trim],
    ];
    if (type === 'hakama') {
      body.push(['M116 288 L72 556 Q118 574 160 566 Q202 574 248 556 L204 288 Z', TOK.body]);
      body.push(['M118 300 L84 552 L112 558 L138 300 Z', TOK.cloth]);
      body.push(['M202 300 L236 552 L208 558 L182 300 Z', TOK.cloth]);
      body.push(['M118 292 L202 292 L206 316 L114 316 Z', TOK.trim]);
      body.push(['M112 550 L112 568 L208 568 L208 550 Z', TOK.trim]);
    } else if (type === 'casual') {
      body.push(['M128 444 L124 578 Q124 592 140 592 Q156 592 154 578 L156 444 Z', TOK.cloth]);
      body.push(['M170 444 L166 578 Q166 592 182 592 Q198 592 196 578 L190 444 Z', TOK.cloth]);
      body.push(['M116 290 L106 452 Q160 468 214 452 L204 290 Z', TOK.body]);
      body.push(['M116 292 L204 292 L206 318 L114 318 Z', TOK.trim]);
      body.push(['M140 186 L180 186 L182 214 L138 214 Z', TOK.dark]);
    } else {
      const hem = type === 'maid' ? 486 : type === 'dress' ? 474 : 456;
      body.push([`M118 288 L84 ${hem} Q120 ${hem + 20} 160 ${hem + 14} Q200 ${hem + 20} 236 ${hem} L202 288 Z`, TOK.body]);
      body.push([`M138 294 L118 ${hem + 6} L160 ${hem + 14} L202 ${hem + 6} L182 294 Z`, TOK.cloth]);
      body.push([`M150 296 L146 ${hem + 12}`, 'none', `stroke="${acc}" stroke-opacity="0.28" stroke-width="1.6"`]);
      body.push([`M170 296 L176 ${hem + 12}`, 'none', `stroke="${acc}" stroke-opacity="0.28" stroke-width="1.6"`]);
      body.push(['M114 286 L206 286 L208 312 L112 312 Z', TOK.trim]);
      body.push(['M150 300 L170 300 L172 330 L148 330 Z', TOK.trim]);
      legs(hem - 4).forEach((s) => body.push(s));
      shoes(602).forEach((s) => body.push(s));
      if (type === 'maid') {
        body.push([`M132 302 L122 ${hem} L198 ${hem} L188 302 Z`, intoNight('#f2f2f2', 0.62)]);
      }
      void sub; void main;
    }
    return body;
  }

  function torso(main, sub, sleeves, acc) {
    const out = [
      ['M160 174 Q198 174 210 200 L216 272 Q160 288 104 272 L110 200 Q122 174 160 174 Z', TOK.body],
      ['M156 150 L164 150 L166 182 L154 182 Z', TOK.dark],
    ];
    if (sleeves === 'puff') {
      out.push(['M112 200 Q74 214 68 266 Q66 298 90 302 Q112 302 110 266 Q114 224 134 214 Z', TOK.cloth]);
      out.push(['M208 200 Q246 214 252 266 Q254 298 230 302 Q208 302 210 266 Q206 224 186 214 Z', TOK.cloth]);
      out.push(['M74 280 Q70 302 92 306 Q112 306 110 284 Z', TOK.trim]);
      out.push(['M246 280 Q250 302 228 306 Q208 306 210 284 Z', TOK.trim]);
      out.push(['M96 300 m-11 0 a11 13 0 1 0 22 0 a11 13 0 1 0 -22 0', TOK.dark]);
      out.push(['M224 300 m-11 0 a11 13 0 1 0 22 0 a11 13 0 1 0 -22 0', TOK.dark]);
    } else {
      out.push(['M112 198 Q94 240 98 306 Q100 330 118 330 Q132 330 130 306 Q128 246 140 210 Z', TOK.body]);
      out.push(['M208 198 Q226 240 222 306 Q220 330 202 330 Q188 330 190 306 Q192 246 180 210 Z', TOK.body]);
      out.push(['M96 296 Q96 322 118 322 Q132 322 130 300 Z', TOK.trim]);
      out.push(['M224 296 Q224 322 202 322 Q188 322 190 300 Z', TOK.trim]);
      out.push(['M108 314 m-10 0 a10 12 0 1 0 20 0 a10 12 0 1 0 -20 0', TOK.dark]);
      out.push(['M212 314 m-10 0 a10 12 0 1 0 20 0 a10 12 0 1 0 -20 0', TOK.dark]);
    }
    void sub; void main; void acc;
    return out;
  }

  function render(spec, opts = {}) {
    const { hair: hairSpec, head, acc, outfit: outfitSpec } = spec;
    const uid = opts.uid || Math.random().toString(36).slice(2, 8);
    const accent = opts.accent || (acc && acc.color) || '#ff9ad5';
    const tone = {
      '@body': `url(#body-${uid})`,
      '@cloth': `url(#cloth-${uid})`,
      '@dark': intoNight(accent, 0.82),
      '@hair': intoNight(hairSpec.color, 0.5),
      '@hairHi': intoNight(hairSpec.color, 0.24),
      '@trim': intoNight(accent, 0.28),
    };
    const parts = { back: [], body: [], head: [], front: [] };
    const push = (bucket, list) => list.forEach((s) => bucket.push(s));

    push(parts.back, hair(hairSpec.style, hairSpec.color, hairSpec.tie || accent, 'behind'));
    push(parts.back, accessory(acc ? acc.type : 'none', (acc && acc.color) || accent, 'behind'));

    const sleeve = ['shrine', 'witch', 'maid', 'dress'].includes(outfitSpec.type) ? 'puff' : 'straight';
    push(parts.body, outfit(outfitSpec.type, outfitSpec.main, outfitSpec.sub, accent));
    push(parts.body, torso(outfitSpec.main, outfitSpec.sub, sleeve, accent));

    push(parts.head, headwear(head ? head.type : 'none', (head && head.color) || accent));
    push(parts.head, hair(hairSpec.style, hairSpec.color, hairSpec.tie || accent, 'head'));
    push(parts.front, accessory(acc ? acc.type : 'none', (acc && acc.color) || accent, 'front'));

    const paint = (list) => list.map(([d, f, e = '']) => {
      const fill = tone[f] || f;
      const extra = f === 'none' ? e : (e || '');
      return `<path d="${d}" fill="${fill}" ${extra}/>`;
    }).join('');

    return `<svg viewBox="0 0 320 640" xmlns="http://www.w3.org/2000/svg" class="youkai-svg" preserveAspectRatio="xMidYMax meet">
<defs>
  <linearGradient id="body-${uid}" x1="0" y1="0" x2="0.35" y2="1">
    <stop offset="0%" stop-color="${mix(accent, '#101425', 0.62)}"/>
    <stop offset="55%" stop-color="${mix(accent, '#080b18', 0.84)}"/>
    <stop offset="100%" stop-color="#05070f"/>
  </linearGradient>
  <linearGradient id="cloth-${uid}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="${mix(accent, '#0c1020', 0.78)}"/>
    <stop offset="100%" stop-color="#070a14"/>
  </linearGradient>
  <radialGradient id="aura-${uid}" cx="50%" cy="46%" r="52%">
    <stop offset="0%" stop-color="${accent}" stop-opacity="0.30"/>
    <stop offset="70%" stop-color="${accent}" stop-opacity="0.06"/>
    <stop offset="100%" stop-color="${accent}" stop-opacity="0"/>
  </radialGradient>
  <filter id="glow-${uid}" x="-30%" y="-30%" width="160%" height="160%">
    <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="${accent}" flood-opacity="0.5"/>
  </filter>
</defs>
<ellipse cx="160" cy="606" rx="112" ry="20" fill="#03040a" opacity="0.85"/>
<ellipse cx="160" cy="330" rx="150" ry="280" fill="url(#aura-${uid})"/>
<g ${opts.glow === false ? '' : `filter="url(#glow-${uid})"`} stroke="${accent}" stroke-opacity="0.45" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round">
  <g opacity="0.9">${paint(parts.back)}</g>
  <g>${paint(parts.body)}</g>
  <g>${paint(parts.head)}</g>
  <g>${paint(parts.front)}</g>
</g>
</svg>`;
  }

  return { render, mix, intoNight };
})();
