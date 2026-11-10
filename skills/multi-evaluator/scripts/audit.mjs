// mStack measured audit: a read only script run in the page, plus the reduced motion check.
// drive.mjs imports runAudit and calls it for the step {"do": "audit"}. Nothing here changes the page.
//
// runAudit(send, ev, scheme, sleep, width) returns the audit as an object; drive.mjs writes it to <out>/audit.json.
//   send   sends one DevTools protocol command; ev evaluates an expression in the page and returns its value.

export const pageAudit = (width) => `(()=>{
  const hex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const parse = (s) => {
    let m = /^rgba?\\(([^)]+)\\)$/.exec(s.trim());
    if (m) { const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = /^color\\(srgb ([^)]+)\\)$/.exec(s.trim());
    if (m) { const p = m[1].split(/[ \\/]+/).filter(Boolean).map(parseFloat); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return [0, 0, 0, 1];
  };
  const over = (top, under) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat([1]); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratioOf = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const backgroundOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) bg = over(layers[i], bg);
    return bg;
  };
  const selectorOf = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && parts.length < 3; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(s + '#' + e.id); break; }
      const cls = (e.getAttribute('class') || '').trim().split(/\\s+/).filter(Boolean)[0];
      if (cls) s += '.' + cls;
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const out = {};
  const vh = window.innerHeight || 1;
  out.screens = Math.round(document.documentElement.scrollHeight / vh * 10) / 10;
  const text = (document.body ? document.body.innerText : '') || '';
  const words = text.toLowerCase().replace(/[^\\p{L}\\p{N}'\\s]/gu, ' ').split(/\\s+/).filter(Boolean);
  out.words = words.length;
  // phrases of four or more words that appear three or more times, longest first, without their own parts
  const kept = [];
  for (let n = Math.min(12, words.length); n >= 4; n--) {
    const seen = new Map();
    for (let i = 0; i + n <= words.length; i++) { const k = words.slice(i, i + n).join(' '); seen.set(k, (seen.get(k) || 0) + 1); }
    for (const [k, c] of seen) if (c >= 3 && !kept.some((x) => x.count >= c && (' ' + x.phrase + ' ').includes(' ' + k + ' '))) kept.push({ phrase: k, count: c });
  }
  out.repeats = kept.sort((a, b) => b.count - a.count || b.phrase.length - a.phrase.length).slice(0, 10);
  const bad = []; const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const done = new Set();
  for (let node = walker.nextNode(); node && bad.length < 40; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!el || done.has(el) || !node.nodeValue.trim() || /^(SCRIPT|STYLE|NOSCRIPT)$/.test(el.tagName)) continue;
    done.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (!el.getClientRects().length || r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    const size = parseFloat(cs.fontSize) || 0;
    if (!size) continue;
    const bg = backgroundOf(el); const fg = over(parse(cs.color), bg);
    const large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight, 10) >= 700);
    const ratio = ratioOf(fg, bg);
    if (ratio < (large ? 3 : 4.5)) bad.push({ text: node.nodeValue.trim().replace(/\\s+/g, ' ').slice(0, 60), fg: hex(fg), bg: hex(bg),
      ratio: Math.round(ratio * 100) / 100, size: Math.round(size * 10) / 10, selector: selectorOf(el) });
  }
  out.contrast = bad;
  const noAlt = [...document.images].filter((i) => i.getAttribute('alt') === null);
  out.images_without_alt = { count: noAlt.length, sources: noAlt.slice(0, 5).map((i) => (i.getAttribute('src') || '').slice(0, 120)) };
  out.sideways_scroll = document.documentElement.scrollWidth > ${width};   // the asked-for width: a mobile page that overflows widens innerWidth
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => +h.tagName[1]);
  out.headings = heads.map((h) => 'h' + h).join(' ');
  out.heading_skips = heads.filter((h, i) => i > 0 && h - heads[i - 1] > 1).length;
  const kb = (b) => Math.round(b / 102.4) / 10;
  const size = (e) => e.transferSize || e.encodedBodySize || e.decodedBodySize || 0;
  const nav = performance.getEntriesByType('navigation')[0];
  out.weight_kb = kb((nav ? size(nav) : 0) + performance.getEntriesByType('resource').reduce((t, e) => t + size(e), 0));
  return out;
})()`;

export const COUNT_MOTION = `(()=>{ let n = 0;
  for (const e of document.querySelectorAll('*')) {
    const cs = getComputedStyle(e); const names = cs.animationName.split(','); const its = cs.animationIterationCount.split(',');
    const play = cs.animationPlayState.split(',');
    if (names.some((x, i) => x.trim() !== 'none' && (its[i % its.length] || '').trim() === 'infinite' && (play[i % play.length] || '').trim() === 'running')) n++;
  }
  return n; })()`;

export async function runAudit(send, ev, scheme, sleep, width) {
  const out = (await ev(pageAudit(width))) || {};
  // count with motion allowed first, whatever this computer's own reduce motion setting is
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme || 'light' },
    { name: 'prefers-reduced-motion', value: 'no-preference' }] });
  await sleep(150);
  const always = await ev(COUNT_MOTION);
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme || 'light' },
    { name: 'prefers-reduced-motion', value: 'reduce' }] });
  await sleep(150);
  const reduced = await ev(COUNT_MOTION);
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme || 'light' },
    { name: 'prefers-reduced-motion', value: 'no-preference' }] });
  out.motion = { always, reduced };
  return out;
}
