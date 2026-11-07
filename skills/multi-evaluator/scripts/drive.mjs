// mStack journey driver: runs a list of steps in a real headless Chrome and saves a screenshot
// and the visible text after every step. Node 18 or later, standard library only.
//
//   node drive.mjs <steps.json> <out-folder>
//
// steps.json:
//   {"viewport": {"w": 1440, "h": 1000, "mobile": false}, "scheme": "light",
//    "thumb": 640,                                          // optional: also save final.jpg at this width
//    "steps": [{"do": "goto", "url": "http://127.0.0.1:8900/"},
//              {"do": "click", "text": "Settings"},          // a visible button, link, row or tab, by its text
//              {"do": "click", "sel": "#save"},              // or by CSS selector
//              {"do": "type", "sel": "input[name=q]", "text": "hello"},
//              {"do": "key", "key": "Tab"},                  // Tab, Enter, Escape, ArrowDown, ArrowUp, Space
//              {"do": "select", "sel": "select", "value": "weekly"},   // an option by its value or its visible text
//              {"do": "wait", "ms": 600},
//              {"do": "shot", "name": "after-save"},         // a named screenshot (one is taken after every step anyway)
//              {"do": "focus"},                              // say which element has keyboard focus
//              {"do": "eval", "js": "document.title"}]}     // any read only check
//
// Output: <out>/NN-<do>.png for every step, and <out>/log.txt (each step's result, the visible text,
// the focused element and any console errors). A step that cannot find its target logs NOT FOUND.
//
// Environment:
//   MSTACK_CDP_PORT  use a Chrome that is already running with --remote-debugging-port=<port>
//                    (for sandboxed reviewers that cannot start Chrome); each run opens and closes its own tab.
//   MSTACK_CHROME    the Chrome or Chromium program to start, if it is not in a usual place.
//   MSTACK_CHROME_ARGS  extra Chrome flags, space separated (for example --no-sandbox in some Linux containers).
import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';

const [, , stepsFile, out] = process.argv;
if (!stepsFile || !out) { console.error('usage: node drive.mjs <steps.json> <out-folder>'); process.exit(2); }
const spec = JSON.parse(fs.readFileSync(stepsFile, 'utf8'));
fs.mkdirSync(out, { recursive: true });
const vp = spec.viewport || { w: 1440, h: 1000, mobile: false };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function findChrome() {
  if (process.env.MSTACK_CHROME) return process.env.MSTACK_CHROME;
  const places = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
    linux: ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser',
      '/snap/bin/chromium'],
    win32: ['C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
      'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'],
  }[process.platform] || [];
  return places.find((p) => fs.existsSync(p)) || null;
}

// A small WebSocket client (enough for the Chrome DevTools protocol), so Node 18 needs nothing extra.
function connect(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url); const key = crypto.randomBytes(16).toString('base64');
    const req = http.request({ host: u.hostname, port: u.port, path: u.pathname + u.search,
      headers: { Connection: 'Upgrade', Upgrade: 'websocket', 'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': key } });
    req.on('error', reject);
    req.on('upgrade', (res, sock, head) => {
      const sockets = { onmessage: null, onclose: null };
      sock.on('error', () => { /* Chrome closing the connection; handled by close */ });
      sock.on('close', () => { if (sockets.onclose) sockets.onclose(); });
      let buf = head && head.length ? Buffer.from(head) : Buffer.alloc(0); let parts = [];
      sock.on('data', (d) => {
        buf = Buffer.concat([buf, d]);
        for (;;) {
          if (buf.length < 2) return;
          const fin = (buf[0] & 0x80) !== 0; const op = buf[0] & 0x0f; let len = buf[1] & 0x7f; let at = 2;
          if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); at = 4; }
          else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); at = 10; }
          const masked = (buf[1] & 0x80) !== 0; const maskAt = at; if (masked) at += 4;
          if (buf.length < at + len) return;
          let payload = buf.subarray(at, at + len);
          if (masked) { const m = buf.subarray(maskAt, maskAt + 4); payload = Buffer.from(payload.map((b, i) => b ^ m[i % 4])); }
          buf = buf.subarray(at + len);
          if (op === 0x8) { sock.end(); return; }
          if (op === 0x9) { send(payload, 0xa); continue; }
          if (op === 0x1 || op === 0x2 || op === 0x0) {
            parts.push(Buffer.from(payload));
            if (fin) { const text = Buffer.concat(parts).toString('utf8'); parts = []; if (sockets.onmessage) sockets.onmessage(text); }
          }
        }
      });
      function send(data, op = 0x1) {
        const payload = Buffer.isBuffer(data) ? data : Buffer.from(String(data), 'utf8'); const n = payload.length;
        const head = n < 126 ? Buffer.alloc(2) : n < 65536 ? Buffer.alloc(4) : Buffer.alloc(10);
        head[0] = 0x80 | op;
        if (n < 126) head[1] = 0x80 | n;
        else if (n < 65536) { head[1] = 0x80 | 126; head.writeUInt16BE(n, 2); }
        else { head[1] = 0x80 | 127; head.writeBigUInt64BE(BigInt(n), 2); }
        const mask = crypto.randomBytes(4); const body = Buffer.from(payload.map((b, i) => b ^ mask[i % 4]));
        sock.write(Buffer.concat([head, mask, body]));
      }
      sockets.send = (s) => send(s);
      sockets.close = () => { try { sock.write(Buffer.from([0x88, 0x80, 0, 0, 0, 0])); sock.end(); } catch { /* closed */ } };
      resolve(sockets);
    });
    req.end();
  });
}

async function getJson(url, method = 'GET') {
  const r = await fetch(url, { method }); return r.json();
}

const shared = process.env.MSTACK_CDP_PORT;
let chrome = null; let work = null; let tabId = null; let wsUrl = null;
const port = shared ? Number(shared) : 9300 + Math.floor(Math.random() * 600);
if (!shared) {
  const bin = findChrome();
  if (!bin) { console.error('Chrome was not found. Install Google Chrome or Chromium, or set MSTACK_CHROME to its program.'); process.exit(3); }
  // Chrome on macOS will not start from the per-user system temp folder, so use /tmp there.
  const base = process.env.MSTACK_TMP || (process.platform === 'darwin' ? '/tmp' : os.tmpdir());
  work = fs.mkdtempSync(path.join(base, 'mstack-chrome-'));
  chrome = spawn(bin, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${work}`, '--hide-scrollbars',
    '--no-first-run', '--no-default-browser-check', ...(process.env.MSTACK_CHROME_ARGS || '').split(' ').filter(Boolean),
    'about:blank'], { stdio: 'ignore' });
}
if (shared) { const t = await getJson(`http://127.0.0.1:${port}/json/new?about:blank`, 'PUT'); wsUrl = t.webSocketDebuggerUrl; tabId = t.id; }
for (let i = 0; i < 100 && !wsUrl; i++) {
  try { wsUrl = (await getJson(`http://127.0.0.1:${port}/json/list`)).find((t) => t.type === 'page')?.webSocketDebuggerUrl; } catch { /* starting */ }
  if (!wsUrl) await sleep(200);
}
if (!wsUrl) { console.error('Could not reach Chrome on port ' + port); if (chrome) chrome.kill('SIGKILL'); process.exit(3); }

const ws = await connect(wsUrl); let id = 0; const pend = new Map(); const errs = [];
ws.onmessage = (data) => {
  const m = JSON.parse(data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result || { error: m.error }); pend.delete(m.id); }
  else if (m.method === 'Runtime.exceptionThrown') errs.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errs.push(m.params.args.map((a) => a.value || a.description).join(' '));
};
ws.onclose = () => { for (const r of pend.values()) r({ error: { message: 'Chrome closed the connection' } }); pend.clear(); };
// Every call answers within a minute, even if Chrome never does.
const send = (method, params = {}) => new Promise((r) => {
  const i = ++id; const t = setTimeout(() => { if (pend.has(i)) { pend.delete(i); r({ error: { message: method + ' timed out' } }); } }, 60000);
  pend.set(i, (v) => { clearTimeout(t); r(v); }); ws.send(JSON.stringify({ id: i, method, params }));
});
const ev = async (x) => (await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true })).result?.value;
const log = [];
const KEYS = { Tab: [9, 'Tab'], Enter: [13, 'Enter'], Escape: [27, 'Escape'], ArrowDown: [40, 'ArrowDown'], ArrowUp: [38, 'ArrowUp'],
  ArrowLeft: [37, 'ArrowLeft'], ArrowRight: [39, 'ArrowRight'], Space: [32, ' '] };
const textOf = `(()=>{const m=document.querySelector('main')||document.body; return (m?m.innerText:'').replace(/\\n{3,}/g,'\\n\\n').slice(0,6000)})()`;
const focusOf = `(()=>{const e=document.activeElement; if(!e||e===document.body) return 'nothing focused'; const t=(e.getAttribute('aria-label')||e.innerText||e.value||'').trim().slice(0,80); return e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+' "'+t+'"'})()`;
function clickJs(step) {
  const q = JSON.stringify(step.text || ''); const sel = JSON.stringify(step.sel || '');
  return `(()=>{let el=null; if(${sel}) el=document.querySelector(${sel}); else { const want=${q}.toLowerCase();
    const c=[...document.querySelectorAll('button,a,[role=button],[role=tab],[role=option],[role=menuitem],[role=link],li[tabindex],[tabindex="0"],summary,label,select,input[type=submit],input[type=button]')]
      .filter(e=>{const r=e.getBoundingClientRect(); return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'});
    const label=e=>(e.innerText||e.value||'').trim().toLowerCase();
    el=c.find(e=>(e.getAttribute('aria-label')||'').toLowerCase()===want)||c.find(e=>label(e)===want)||c.find(e=>label(e).includes(want)); }
    if(!el) return 'NOT FOUND'; el.scrollIntoView({block:'center'}); el.focus&&el.focus(); el.click();
    return 'clicked '+el.tagName.toLowerCase()+' "'+(el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,60)+'"'})()`;
}

let failed = false;
try {
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: spec.scheme || 'light' }] });
  const dsf = vp.mobile ? 2 : 1;
  await send('Emulation.setDeviceMetricsOverride', { width: vp.w, height: vp.h, deviceScaleFactor: dsf, mobile: !!vp.mobile });
  if (vp.mobile) await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  let n = 0;
  for (const step of spec.steps) {
    n++; let res = '';
    if (step.do === 'goto') { await send('Page.navigate', { url: step.url }); await sleep(step.ms || 1500); res = 'opened ' + step.url; }
    else if (step.do === 'click') { res = await ev(clickJs(step)); await sleep(step.ms || 700); }
    else if (step.do === 'type') {
      res = await ev(`(()=>{const e=document.querySelector(${JSON.stringify(step.sel)}); if(!e) return 'NOT FOUND'; e.focus(); e.value=${JSON.stringify(step.text)}; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true})); return 'typed'})()`);
      await sleep(step.ms || 400);
    } else if (step.do === 'select') {
      // match an option by its value or its visible text (trimmed, case does not matter), fire the events a
      // real choice fires, and say NOT FOUND with the options when nothing matches instead of clearing the choice
      res = await ev(`(()=>{const e=document.querySelector(${JSON.stringify(step.sel)}); if(!e) return 'NOT FOUND';
        const want=String(${JSON.stringify(step.value)}).trim().toLowerCase();
        const opts=[...e.querySelectorAll('option')];
        const o=opts.find(o=>o.value===${JSON.stringify(step.value)})||opts.find(o=>o.value.trim().toLowerCase()===want)||opts.find(o=>o.textContent.trim().toLowerCase()===want);
        if(!o) return 'NOT FOUND: no option matches '+JSON.stringify(${JSON.stringify(step.value)})+'; options: '+opts.map(o=>JSON.stringify(o.textContent.trim())).join(', ');
        e.value=o.value; e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));
        return 'selected '+JSON.stringify(o.textContent.trim())+' (value '+JSON.stringify(o.value)+')'})()`);
      await sleep(step.ms || 900);
    } else if (step.do === 'key') {
      const [code, key] = KEYS[step.key] || [0, step.key];
      for (const type of ['keyDown', 'keyUp']) {
        await send('Input.dispatchKeyEvent', { type, key, code: key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code,
          text: type === 'keyDown' && key.length === 1 ? key : undefined });
      }
      await sleep(step.ms || 350); res = 'pressed ' + step.key + '; focus: ' + (await ev(focusOf));
    } else if (step.do === 'wait') { await sleep(step.ms || 500); res = 'waited'; }
    else if (step.do === 'focus') res = 'focus: ' + (await ev(focusOf));
    else if (step.do === 'eval') res = JSON.stringify(await ev(step.js));
    else if (step.do === 'shot') res = 'screenshot';
    else res = 'NOT FOUND: unknown step "' + step.do + '"';
    if (String(res).startsWith('NOT FOUND')) failed = true;
    const name = `${String(n).padStart(2, '0')}-${step.name || step.do}`;
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    if (!shot.data) throw new Error('Chrome did not return a screenshot: ' + JSON.stringify(shot.error || shot));
    fs.writeFileSync(path.join(out, name + '.png'), Buffer.from(shot.data, 'base64'));
    log.push(`\n=== step ${n} ${JSON.stringify(step)}\nresult: ${res}\nscreenshot: ${name}.png\nvisible text:\n${await ev(textOf)}`);
  }
  if (spec.thumb) {   // a smaller JPEG of the final screen, for reports
    const scale = Math.min(1, spec.thumb / (vp.w * dsf));   // the JPEG comes out spec.thumb pixels wide
    const t = await send('Page.captureScreenshot', { format: 'jpeg', quality: 72,
      clip: { x: 0, y: 0, width: vp.w, height: vp.h, scale } });
    fs.writeFileSync(path.join(out, 'final.jpg'), Buffer.from(t.data, 'base64'));
  }
} finally {
  log.push('\nconsole errors: ' + (errs.length ? errs.join('\n') : 'none'));
  fs.writeFileSync(path.join(out, 'log.txt'), log.join('\n'));
  ws.close();
  if (shared) { try { await fetch(`http://127.0.0.1:${port}/json/close/${tabId}`); } catch { /* gone */ } }
  else { chrome.kill('SIGKILL'); await sleep(300); try { fs.rmSync(work, { recursive: true, force: true, maxRetries: 5 }); } catch { /* busy */ } }
}
console.log('done: ' + path.join(out, 'log.txt') + (failed ? ' (a step did not find its target)' : ''));
process.exit(0);
