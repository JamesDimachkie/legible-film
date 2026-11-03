#!/usr/bin/env node
/** Deterministic Playwright capture worker for the window.__lf page contract. */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {inflateSync} from 'node:zlib';
import {once} from 'node:events';
import http from 'node:http';
import {spawnSync} from 'node:child_process';

let activeBrowser;
async function stopOnPipe() {
  try { if (activeBrowser) await activeBrowser.close(); } finally { process.exit(2); }
}
process.stdout.on('error', e => { if (e.code === 'EPIPE') void stopOnPipe(); else throw e; });
process.on('SIGTERM', () => { void stopOnPipe(); });

const HELP = `Capture a local film page implementing window.__lf (Node 18+, Playwright, Chromium).

  node film_capture.mjs info http://127.0.0.1:8000/?render
  node film_capture.mjs analyse --url http://127.0.0.1:8000/?render
  node film_capture.mjs frames URL --from 0 --to 59 --samples 4 --shutter 180 > samples.lf
  node film_capture.mjs stills URL --at 1.0,2.5,b12 --out qa/stills
  node film_capture.mjs calibrate
  node film_capture.mjs cues film/ --out cues.json [--source lf|declared|timelines] [--verify]

cues writes cues.json v2 from the page's own declarations; node film_capture.mjs cues --help.

--from/--to are inclusive zero-based output frame indices. --scale is device scale
(default 1). --format png|jpeg, --quality 92, --max-samples 32. --url or LF_URL.
--size WxH sets w/h URL parameters and the CSS viewport for info/analyse/frames/stills.
The page must report that size in info(); device scale still multiplies it.
--playwright PATH (or LF_PLAYWRIGHT_MODULE) chooses an installed package; otherwise
resolve playwright/core from cwd or this script. --browser PATH (or LF_CHROMIUM)
chooses Chromium; otherwise use Playwright's installed build or the newest cached
Chromium in LOCALAPPDATA/ms-playwright (PLAYWRIGHT_BROWSERS_PATH overrides cache).
No browser download. --compositor off disables the compositor switch for experiments.

frames writes binary LF01 followed by records: uint32BE JSON byte length, JSON UTF-8,
uint32BE image byte length, image bytes. info record first, samples in frame order,
done record last. Bounded writes respect stdout backpressure. Diagnostics go to stderr.
All other commands print JSON. Samples average elsewhere; no audio is captured.
Samples use centred exposure, cut-aware sliding, smear/fast windows, midpoint sampling.
One browser per invocation, closed even on failure. Only local HTTP assets allowed;
after __lf.ready no new page requests are allowed. Seeks wait two paints; no film clock
is advanced by wall time. Cannot prove a page itself obeys purity or judge playback.
Exit 0 complete, 2 input/dependency/page/console/capture error (including calibration FAIL).
`;

function args(argv) {
  const a = {command: argv.shift()};
  const options=new Set(['url','from','to','shutter','samples','max-samples','scale','format','quality','at','out','playwright','browser','compositor','size']);
  while (argv.length) {
    const x = argv.shift();
    if (x === '--help' || x === '-h') a.help = true;
    else if (x.startsWith('--')) {
      if(!options.has(x.slice(2)))throw Error(`unknown option ${x}`);
      if (!argv.length || argv[0].startsWith('--')) throw Error(`missing value for ${x}`);
      a[x.slice(2)] = argv.shift();
    } else if (!a.url) a.url = x;
    else throw Error(`unexpected argument ${x}`);
  }
  return a;
}
function number(a, key, fallback, min = -Infinity, integer = false) {
  const v = Number(a[key] ?? fallback);
  if (!Number.isFinite(v) || v < min || (integer && !Number.isInteger(v))) throw Error(`invalid --${key}`);
  return v;
}
async function playwright(a) {
  function load(req,name) {
    const api=req(name);let dir=path.dirname(req.resolve(name));let version='unknown';
    for(let i=0;i<5;i++) {
      const pkg=path.join(dir,'package.json');
      if(fs.existsSync(pkg)) { const meta=JSON.parse(fs.readFileSync(pkg,'utf8')); if(['playwright','playwright-core'].includes(meta.name)){version=meta.version;break;} }
      dir=path.dirname(dir);
    }
    return {api,version};
  }
  if (a.playwright || process.env.LF_PLAYWRIGHT_MODULE) {
    try { return load(createRequire(import.meta.url),path.resolve(a.playwright || process.env.LF_PLAYWRIGHT_MODULE)); }
    catch(e) { if(e.code==='MODULE_NOT_FOUND')throw Error('Playwright missing: cannot load the explicit package path'); throw e; }
  }
  const userKit = () => path.join(process.platform === 'win32'
    ? (process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'))
    : (process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share')),
    'legible-film', 'playwright', 'package.json');
  // setup.py installs playwright-core under the user's data folder: look there after the project and the kit.
  for (const root of [path.join(process.cwd(), 'package.json'), fileURLToPath(import.meta.url),
                      userKit()]) {
    const req = createRequire(root);
    for (const name of ['playwright', 'playwright-core']) {
      try { return load(req,name); } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
    }
  }
  throw Error('Playwright missing: run setup.py for the install command, or give --playwright PATH');
}
function browserPath(pw, a) {
  const explicit = a.browser || process.env.LF_CHROMIUM;
  if (explicit) { if (!fs.existsSync(explicit)) throw Error('Chromium executable missing'); return explicit; }
  if (fs.existsSync(pw.chromium.executablePath())) return pw.chromium.executablePath();
  // Playwright's own default cache per system: Windows LOCALAPPDATA, macOS ~/Library/Caches, Linux ~/.cache.
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(process.platform === 'win32'
    ? (process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'))
    : process.platform === 'darwin' ? path.join(os.homedir(), 'Library', 'Caches') : path.join(os.homedir(), '.cache'),
    'ms-playwright');
  const builds = fs.existsSync(cache) ? fs.readdirSync(cache).filter(x => /^chromium-\d+$/.test(x))
    .sort((a,b) => Number(b.split('-')[1]) - Number(a.split('-')[1])) : [];
  for (const build of builds) for (const exe of ['chrome-win64/chrome.exe','chrome-win/chrome.exe','chrome-linux/chrome',
    'chrome-linux64/chrome','chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    'chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium']) {
    const p = path.join(cache, build, exe); if (fs.existsSync(p)) return p;
  }
  throw Error(`Chromium missing in ${cache}; set --browser PATH`);
}
function validate(info) {
  for (const key of ['width','height','fps','duration','frames'])
    if (!Number.isFinite(info[key]) || info[key] <= 0) throw Error(`invalid info.${key}`);
  if (!['width','height','frames'].every(k => Number.isInteger(info[k])) || info.frames !== Math.round(info.duration * info.fps))
    throw Error('invalid dimensions or frame count');
  const cuts = info.cuts || [];
  if (cuts.some((c,i) => !Number.isFinite(c) || c <= 0 || c >= info.duration || (i && c <= cuts[i-1]))) throw Error('invalid cuts');
  for (const key of ['smears','fast']) for (const row of info[key] || [])
    if (row.length !== 3 || !row.every(Number.isFinite) || row[0] < 0 || row[1] <= row[0] || row[1] > info.duration || row[2] < 1 || (key === 'fast' && !Number.isInteger(row[2]))) throw Error(`invalid ${key}`);
}
export function sampleTimes(t, info, shutter, base, maximum) {
  const factor = Math.max(1, ...(info.smears || []).filter(([a,b]) => a <= t && t < b).map(x => x[2]));
  const n = Math.min(maximum, Math.max(base, Math.ceil(base * factor), 1,
    ...(info.fast || []).filter(([a,b]) => a <= t && t < b).map(x => x[2])));
  if (n === 1 || shutter === 0) return [t];
  const e = shutter / 360 / info.fps * factor;
  let lo = Math.max(0, t - e / 2), hi = Math.min(info.duration, t + e / 2);
  const cuts = info.cuts || [], before = cuts.filter(c => c <= t), after = cuts.find(c => c > t);
  const left = before.length ? before[before.length-1] : 0, right = after ?? info.duration;
  const length = Math.min(hi-lo, right-left);
  lo = Math.max(left, Math.min(lo, right-length));
  return Array.from({length:n}, (_,k) => lo + (k+.5)*length/n);
}
async function write(buffer) { if (!process.stdout.write(buffer)) await once(process.stdout, 'drain'); }
async function record(meta, data = Buffer.alloc(0)) {
  const j = Buffer.from(JSON.stringify(meta)), h = Buffer.alloc(4), d = Buffer.alloc(4);
  h.writeUInt32BE(j.length); d.writeUInt32BE(data.length);
  await write(h); await write(j); await write(d); if (data.length) await write(data);
}
// A page that never becomes ready, or a frame that never paints, stops the job with a reason instead of hanging it.
const READY_MS = Number(process.env.LF_READY_TIMEOUT_MS || 60000);
const FRAME_MS = Number(process.env.LF_FRAME_TIMEOUT_MS || 60000);
function within(promise, ms, what) {
  let timer;
  const deadline = new Promise((_, reject) => { timer = setTimeout(() => reject(Error(`${what} did not finish within ${ms} ms`)), ms); });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}
async function paint(page, t, frame) {
  await within(page.evaluate(async ({t, frame}) => {
    if (frame !== undefined) window.__lf.frame(frame);
    window.__lf.seek(t);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, {t, frame}), FRAME_MS, `painting t=${t} (window.__lf.seek)`);
}
function pngPixels(buf) {
  const {w,h,channels,out}=pngDecode(buf), stride=w*channels;
  return {w,h,pixel:(x,y)=>Array.from(out.subarray(y*stride+x*channels,y*stride+x*channels+3))};
}
function pngDecode(buf) {
  let pos = 8, w, h, channels, compressed = [];
  while (pos < buf.length) {
    const size = buf.readUInt32BE(pos), type = buf.toString('ascii',pos+4,pos+8), data = buf.subarray(pos+8,pos+8+size);
    if (type === 'IHDR') { w=data.readUInt32BE(0); h=data.readUInt32BE(4); channels = data[9] === 6 ? 4 : data[9] === 2 ? 3 : 0; if(data[8]!==8 || !channels || data[12]) throw Error('unsupported PNG'); }
    if (type === 'IDAT') compressed.push(data); pos += size+12;
  }
  const raw=inflateSync(Buffer.concat(compressed)), stride=w*channels, out=Buffer.alloc(h*stride);
  let p=0;
  for(let y=0;y<h;y++) { const filter=raw[p++]; for(let x=0;x<stride;x++) {
    const a=x>=channels?out[y*stride+x-channels]:0, b=y?out[(y-1)*stride+x]:0, c=y&&x>=channels?out[(y-1)*stride+x-channels]:0;
    let pred=0;
    if(filter===1)pred=a; else if(filter===2)pred=b; else if(filter===3)pred=Math.floor((a+b)/2);
    else if(filter===4) { const q=a+b-c, pa=Math.abs(q-a),pb=Math.abs(q-b),pc=Math.abs(q-c); pred=pa<=pb&&pa<=pc?a:pb<=pc?b:c; }
    else if(filter!==0)throw Error('bad PNG filter');
    out[y*stride+x]=(raw[p++]+pred)&255;
  }}
  return {w,h,channels,out};
}
const CAL = `<!doctype html><style>*{box-sizing:border-box}html,body{margin:0;width:320px;height:180px;background:#263544;overflow:hidden}#border{position:absolute;inset:0;border:1px solid white;z-index:4}.mark{position:absolute;width:8px;height:8px;z-index:5}.layer{position:absolute;left:20px;top:20px;width:280px;height:140px;background:#00cc66;transform:perspective(900px) rotateY(.01deg);will-change:transform}#type{position:absolute;left:60px;top:70px;font:20px Arial;color:white;z-index:3}</style><div class=layer id=layer></div><div id=type>FONTS READY</div><div id=border></div><div class=mark style="left:1px;top:1px;background:red"></div><div class=mark style="right:1px;top:1px;background:lime"></div><div class=mark style="left:1px;bottom:1px;background:blue"></div><div class=mark style="right:1px;bottom:1px;background:yellow"></div><script>window.__lf={ready:document.fonts.ready,info:()=>({width:320,height:180,fps:60,duration:1,frames:60,cuts:[]}),frame:()=>{},seek:t=>{document.querySelector('#layer').style.transform='perspective(900px) rotateY(.01deg) translateX('+(t*2)+'px)'}};</script>`;

async function main() {
  if (process.argv[2] === 'cues') { process.exitCode = await cuesMain(process.argv.slice(3)); return; }
  const a = args(process.argv.slice(2));
  if (a.help || a.command === '--help' || !a.command) { console.log(HELP); return; }
  if (!['info','analyse','frames','stills','calibrate'].includes(a.command)) throw Error('unknown command');
  let requestedSize=null;
  if(a.size) {
    const m=/^(\d+)[xX](\d+)$/.exec(a.size);
    if(!m||Number(m[1])<2||Number(m[2])<2||!Number.isSafeInteger(Number(m[1]))||!Number.isSafeInteger(Number(m[2])))throw Error('--size must be WxH, at least 2 pixels per side');
    requestedSize={width:Number(m[1]),height:Number(m[2])};
    if(a.command==='calibrate')throw Error('--size applies to page commands, not calibrate');
  }
  const scale=number(a,'scale',1,.01), shutter=number(a,'shutter',180,0), samples=number(a,'samples',4,1,true), maximum=number(a,'max-samples',32,1,true);
  const quality=number(a,'quality',92,0,true); if (quality>100)throw Error('quality must be <=100');
  if (!['png','jpeg'].includes(a.format || 'png'))throw Error('format must be png or jpeg');
  const loaded=await playwright(a), pw=loaded.api, exe=browserPath(pw,a);
  const browser=await pw.chromium.launch({executablePath:exe,headless:true,args:[
    '--force-color-profile=srgb','--disable-background-timer-throttling','--disable-renderer-backgrounding',
    ...(a.compositor==='off'?[]:['--run-all-compositor-stages-before-draw'])]});
  activeBrowser=browser;
  const errors=[]; let frozen=false;
  try {
    if (a.command==='calibrate') {
      const checks=[];
      for(const s of [1,2]) {
        const ctx=await browser.newContext({viewport:{width:320,height:180},deviceScaleFactor:s,serviceWorkers:'block'}), page=await ctx.newPage();
        page.on('pageerror',e=>errors.push(`page error: ${e.message}`)); page.on('console',m=>{if(m.type()==='error')errors.push(`console error: ${m.text()}`)});
        await page.setContent(CAL); await page.evaluate(()=>window.__lf.ready); await paint(page,0,null);
        const snap=await page.screenshot({type:'png',scale:'device',clip:{x:0,y:0,width:320,height:180}}), pix=pngPixels(snap);
        const check=(name,ok,detail)=>checks.push({name:`scale ${s}: ${name}`,status:ok?'PASS':'FAIL',detail});
        const eq=(x,y,rgb)=>pix.pixel(x,y).every((v,i)=>v===rgb[i]);
        check('pixel size',pix.w===320*s&&pix.h===180*s,[pix.w,pix.h]);
        const css=pngPixels(await page.screenshot({type:'png',scale:'css',clip:{x:0,y:0,width:320,height:180}}));
        check('CSS-scale capture is explicitly lower resolution',css.w===320&&css.h===180,[css.w,css.h]);
        const cdp=await ctx.newCDPSession(page);
        const raw=await cdp.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,clip:{x:0,y:0,width:320,height:180,scale:1}});
        const rawPix=pngPixels(Buffer.from(raw.data,'base64'));
        check('CDP clip with scale 1 measured',[320,320*s].includes(rawPix.w),[rawPix.w,rawPix.h]);
        check('four corner markers',[[4,4,[255,0,0]],[315,4,[0,255,0]],[4,175,[0,0,255]],[315,175,[255,255,0]]].every(([x,y,c])=>eq(x*s,y*s,c)));
        const edges=[...Array(pix.w).keys()].every(x=>eq(x,0,[255,255,255])&&eq(x,pix.h-1,[255,255,255]))&&[...Array(pix.h).keys()].every(y=>eq(0,y,[255,255,255])&&eq(pix.w-1,y,[255,255,255]));
        check('one-pixel border / no missing edge',edges);
        check('large transformed layer',[[25,25],[290,25],[25,150],[290,150],[160,145]].every(([x,y])=>eq(x*s,y*s,[0,204,102])));
        check('fonts loaded',await page.evaluate(()=>document.fonts.status==='loaded'&&document.fonts.check('20px Arial')));
        await paint(page,.7,null); const first=await page.screenshot({scale:'device'});
        for(const t of [.1,.9,.3,.7])await paint(page,t,null);
        const last=await page.screenshot({scale:'device'});
        check('out-of-order seek identical',createHash('sha256').update(first).digest('hex')===createHash('sha256').update(last).digest('hex'));
        await ctx.close();
      }
      const ctx=await browser.newContext({viewport:{width:1920,height:1080},deviceScaleFactor:1}), page=await ctx.newPage();
      page.on('pageerror',e=>errors.push(`page error: ${e.message}`));
      page.on('console',m=>{if(m.type()==='error')errors.push(`console error: ${m.text()}`)});
      await page.setContent('<style>html,body{margin:0;overflow:hidden;background:#263544}#p{position:absolute;left:-960px;top:-540px;width:3840px;height:2160px;background:#00cc66;will-change:transform;transform:perspective(9000px) rotateY(.01deg)}</style><div id=p></div>');
      let filled=true;
      for(const x of [0,3,-4,0]) {
        await page.evaluate(async x=>{document.querySelector('#p').style.transform=`perspective(9000px) rotateY(.01deg) translateX(${x}px)`;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))},x);
        const pix=pngPixels(await page.screenshot({scale:'device'}));
        for(let y=0;y<1080;y+=53)for(let x=0;x<1920;x+=71)if(pix.pixel(x,y).join(',')!=='0,204,102')filled=false;
        for(let x=0;x<1920;x++)if(pix.pixel(x,1079).join(',')!=='0,204,102')filled=false;
        for(let y=0;y<1080;y++)if(pix.pixel(1919,y).join(',')!=='0,204,102')filled=false;
      }
      checks.push({name:'1080p oversized 3D layer repeated repaint',status:filled?'PASS':'FAIL',detail:'3840x2160 CSS layer, 1920x1080 capture; grid includes edges'});
      await ctx.close();
      console.log(JSON.stringify({browser:browser.version(),playwright:loaded.version,executable:exe,compositor:a.compositor!=='off',checks,errors},null,2));
      if(errors.length||checks.some(x=>x.status==='FAIL'))throw Error('calibration FAIL'); return;
    }
    const url=new URL(a.url||process.env.LF_URL||'');
    if(url.protocol!=='http:'||url.hostname!=='127.0.0.1')throw Error('page must be http://127.0.0.1:<port>/');
    if(requestedSize) {url.searchParams.set('w',String(requestedSize.width));url.searchParams.set('h',String(requestedSize.height));}
    const context=await browser.newContext({viewport:requestedSize||{width:1920,height:1080},deviceScaleFactor:scale,serviceWorkers:'block'});
    await context.route('**/*',async route=>{const u=new URL(route.request().url());
      if(frozen||u.origin!==url.origin) {errors.push(`forbidden page request: ${u.origin}${u.pathname}`); await route.abort();} else await route.continue();});
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(`page error: ${e.message}`));
    page.on('console',m=>{if(m.type()==='error')errors.push(`console error: ${m.text()}`)});
    await page.goto(url.href,{waitUntil:'load'});
    await page.waitForFunction(()=>!!window.__lf,{},{timeout:30000});
    await within(page.evaluate(async()=>{await window.__lf.ready; await document.fonts.ready;}), READY_MS,
      'the page (window.__lf.ready and its fonts; raise LF_READY_TIMEOUT_MS for a slow page)');
    const info=await page.evaluate(()=>window.__lf.info()); validate(info);
    if(requestedSize&&(info.width!==requestedSize.width||info.height!==requestedSize.height))throw Error('page info size does not honour --size w/h parameters');
    await page.setViewportSize({width:info.width,height:info.height});
    await paint(page,0,null); frozen=true;
    function clean(){if(errors.length)throw Error(errors.join('\n'));}
    clean();
    if(a.command==='info'||a.command==='analyse') {
      const value=a.command==='info'?info:await page.evaluate(()=>{if(!window.__lf.analyse)throw Error('__lf.analyse is not implemented');return window.__lf.analyse();});
      clean();console.log(JSON.stringify(value));
    } else if(a.command==='stills') {
      if(!a.at||!a.out)throw Error('stills needs --at and --out');fs.mkdirSync(a.out,{recursive:true});const files=[];
      for(const [i,value] of a.at.split(',').entries()) {
        const beat=value.startsWith('b');if(beat&&!info.beat)throw Error('page has no beat grid');
        const t=beat?Number(value.slice(1))*60/info.beat.bpm+info.beat.offset:Number(value);
        if(!Number.isFinite(t)||t<0||t>info.duration)throw Error(`invalid still time ${value}`);
        await paint(page,t,null);const file=path.join(a.out,`still-${String(i).padStart(3,'0')}-${t.toFixed(6)}.png`);
        await page.screenshot({path:file,type:'png',scale:'device'});clean();files.push(file);
      }
      console.log(JSON.stringify({files,browser:browser.version(),playwright:loaded.version}));
    } else {
      const from=number(a,'from',0,0,true), to=number(a,'to',info.frames-1,0,true);
      if(to<from||to>=info.frames)throw Error('invalid output frame range');
      await write(Buffer.from('LF01'));await record({kind:'info',info,browser:browser.version(),playwright:loaded.version,executable:exe,scale});
      for(let k=from;k<=to;k++) {
        const t=k/info.fps, times=sampleTimes(t,info,shutter,samples,maximum);
        await page.evaluate(t=>window.__lf.frame(t),t);
        for(let j=0;j<times.length;j++) {
          await paint(page,times[j]);
          const data=await page.screenshot({type:a.format||'png',scale:'device',...(a.format==='jpeg'?{quality}: {})});clean();
          await record({kind:'sample',frame:k,sample:j,count:times.length,time_s:times[j]},data);
        }
      }
      await page.evaluate(()=>window.__lf.frame(null));clean();await record({kind:'done',frames:to-from+1});
    }
    await context.close();
  } finally { await browser.close(); activeBrowser=undefined; }
}
// ---------- cues: export cues.json v2 from the page's own declarations ----------
const CUE_HELP = `Export cues.json v2 from what owns the timeline (Node 18+, Playwright, Chromium, Python 3.9+).

  node film_capture.mjs cues film/ --out film/cues.json --source timelines --verify
  node film_capture.mjs cues film/ --out cues.json --source declared --ready __cues_ready --global __cues --fps 60
  node film_capture.mjs cues http://127.0.0.1:8000/index.html?render --root film/ --out cues.json --source lf

Sources. lf: the kit's window.__lf.info().cues. declared: window[--global] (default __cues) once window[--ready]
(default __cues_ready) is true; an entry may name a timeline label in place of t. timelines: the HyperFrames page's
GSAP labels (cue:<id>, cue:<id>:end, section:<id>, section:<id>:end on window.__timelines[<data-composition-id>],
offset by the composition's data-start) merged by id with the <script type="application/json" id="lf-cues"> block.
Without --source: timelines when the block exists, else lf when window.__lf exists, else declared.

Closure. The page is frozen first (python cue_list.py freeze: pinned URLs vendored, outside files copied in), and the
export loads that frozen copy as the server root with every request intercepted. A request that leaves the copy is
recorded (and let through, so the page still exports); so is a path the copy does not hold. The list records the page fingerprint, source_files and the
copy's snapshot_sha256, and the copy stays at PAGE/.lf-frozen/<snapshot_sha256>/ for the render. An unpinned URL, a
../ or absolute reference, a request the copy does not hold, or text drawn in a system font exports binding: unverified.

--verify seeks t-1f, t and t+1f at each turn and contact and flags "no frame change" as a look (exit 1); cues
declared picture: none or picture: held are skipped and listed; held without a decision is exit 2. --candidates
lists motion peaks as unconfirmed hints, with export.candidates_scan saying how the scan went: found, none (the
picture moves but no change stands out from its surrounding second) or inconclusive (every sample matched the one
before it: nothing moved, or the capture did not paint; a look, exit 1). A sample whose seek or capture fails is exit 2
naming it, and no list is written: an empty candidate list always means a scan that ran. --fps N (or a rational) and --size WxH override the page's own values.
--python sets the interpreter (default LF_PYTHON, else python3; python on Windows). --playwright and --browser as for
the other commands. The output may not alias an input, sit inside a kept copy, or sit inside a version folder.

Exit 0 written; 1 written with a look (--verify); 2 the page could not load, the declaration is incomplete or
inconsistent (names given), or the output is refused.
`;
const CUE_VALUES = new Set(['out','source','ready','global','fps','size','root','python','playwright','browser']);
const CUE_FLAGS = new Set(['verify','candidates']);
const SCALES = new Set(['turn','follow','contact','silence']);
const SPANS = new Set(['follow','silence']);
const CLOCKS = new Set(['speech','music','action','silence']);
const SYNCS = new Set(['attack','apex','end']);
const SOUNDS = new Set(['required','silent','optional']);
const SCOPES = new Set(['new','effects','all']);
const EVENT_KEYS = ['id','t','t_end','scale','sync','lead_ms','section','sound','role','hero','decision','picture','x','y',
  'pan','pitch_st','gain_db','tolerance_ms','run','intent','span','scope','duck_db','variant','label'];
const MIME = {'.html':'text/html; charset=utf-8','.htm':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript',
  '.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg',
  '.webp':'image/webp','.gif':'image/gif','.avif':'image/avif','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf',
  '.otf':'font/otf','.mp4':'video/mp4','.webm':'video/webm','.mov':'video/quicktime','.wav':'audio/wav','.mp3':'audio/mpeg',
  '.m4a':'audio/mp4','.ogg':'audio/ogg','.txt':'text/plain','.wasm':'application/wasm','.csv':'text/csv'};
const HERE = path.dirname(fileURLToPath(import.meta.url));

class Refusal extends Error {}
function refuse(msg) { return new Refusal(msg); }

function cueArgs(argv) {
  const a = {};
  while (argv.length) {
    const x = argv.shift();
    if (x === '--help' || x === '-h') a.help = true;
    else if (x.startsWith('--')) {
      const name = x.slice(2);
      if (CUE_FLAGS.has(name)) a[name] = true;
      else if (CUE_VALUES.has(name)) { if (!argv.length) throw refuse(`missing value for ${x}`); a[name] = argv.shift(); }
      else throw refuse(`unknown option ${x}`);
    } else if (!a.target) a.target = x;
    else throw refuse(`unexpected argument ${x}`);
  }
  return a;
}

function fpsValue(v) {
  if (v == null || v === '') return null;
  const text = String(v).trim();
  const m = /^(\d+(?:\.\d+)?)(?:\/(\d+(?:\.\d+)?))?$/.exec(text);
  if (!m) throw refuse(`invalid fps ${text}`);
  const value = m[2] ? Number(m[1]) / Number(m[2]) : Number(m[1]);
  if (!(value > 0) || !Number.isFinite(value)) throw refuse(`invalid fps ${text}`);
  return {value, stored: m[2] ? text : (Number.isInteger(value) ? value : value)};
}

// Custody: the same rule as project.py refuse_overwriting_inputs, for this writer.
function realish(p) {
  let cur = path.resolve(p); const rest = [];
  while (!fs.existsSync(cur)) { rest.unshift(path.basename(cur)); const up = path.dirname(cur); if (up === cur) break; cur = up; }
  let real = cur; try { real = fs.realpathSync.native(cur); } catch { /* keep the resolved path */ }
  return path.join(real, ...rest);
}
const fold = p => (process.platform === 'win32' || process.platform === 'darwin') ? p.toLowerCase() : p;
function samePath(x, y) { return fold(realish(x)) === fold(realish(y)); }
function inside(child, parent) {
  const c = fold(realish(child)), p = fold(realish(parent));
  return c === p || c.startsWith(p.endsWith(path.sep) ? p : p + path.sep);
}
function versionFolder(p) {
  let cur = path.dirname(realish(p));
  for (;;) {
    if (/^v\d{3,}$/.test(path.basename(cur)) && path.basename(path.dirname(cur)).toLowerCase() === 'cuts' &&
        fs.existsSync(path.join(cur, 'manifest.json'))) return cur;
    const up = path.dirname(cur); if (up === cur) return null; cur = up;
  }
}
function refuseOutput(out, inputs, pageDir) {
  if (fs.existsSync(out) && fs.statSync(out).isDirectory()) throw refuse(`the output ${out} is a folder; name a file`);
  for (const input of inputs) if (input && samePath(out, input)) throw refuse(`the output ${out} is the input ${input}; write it to another file`);
  const version = versionFolder(out);
  if (version) throw refuse(`the output ${out} is inside the version folder ${version}, which is immutable; write it elsewhere`);
  if (inside(out, path.join(pageDir, '.lf-frozen'))) throw refuse(`the output ${out} is inside a kept frozen copy; write it elsewhere`);
}

function pythonFor(a) { return a.python || process.env.LF_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'); }

// One freeze implementation serves every exporter: cue_list.py freeze.
function freezePage(dir, a, entry) {
  const script = path.join(HERE, 'cue_list.py');
  if (!fs.existsSync(script)) throw Error('cue_list.py is missing beside film_capture.mjs');
  const r = spawnSync(pythonFor(a), [script, 'freeze', dir, '--json', '--entry', entry], {encoding:'utf8', maxBuffer:256*1024*1024});
  if (r.error) throw Error(`could not run Python (${pythonFor(a)}): ${r.error.message}; give --python PATH`);
  if (r.status) throw Error('cue_list.py freeze: ' + ((r.stderr || r.stdout || '').trim().split('\n').slice(-3).join(' ') || `exit ${r.status}`));
  return JSON.parse(r.stdout);
}

// Files the page loaded at export that freeze's static walk did not reach are scanned here, by the same rule.
function scanLoaded(dir, files, a) {
  if (!files.length) return {files: [], reasons: []};
  const r = spawnSync(pythonFor(a), [path.join(HERE, 'cue_list.py'), 'scan', dir, ...files, '--json'],
    {encoding:'utf8', maxBuffer:64*1024*1024});
  if (r.error || r.status) throw Error('cue_list.py scan: ' + ((r.stderr || r.stdout || '').trim().split('\n').slice(-2).join(' ') || `exit ${r.status}`));
  return JSON.parse(r.stdout);
}

async function serveFolder(root) {
  const seen = [];
  const base = path.resolve(root);
  const server = http.createServer((req, res) => {
    let rel;
    try { rel = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname); } catch { res.writeHead(400); res.end(); return; }
    if (rel.endsWith('/')) rel += 'index.html';
    const file = path.resolve(base, '.' + rel);
    let ok = false;
    if (file === base || file.startsWith(base + path.sep)) { try { ok = fs.statSync(file).isFile(); } catch { ok = false; } }
    seen.push({path: rel, status: ok ? 200 : 404});
    if (!ok) { res.writeHead(404, {'Cache-Control':'no-store'}); res.end(); return; }
    res.writeHead(200, {'Content-Type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream', 'Cache-Control':'no-store'});
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  return {server, origin: `http://127.0.0.1:${server.address().port}`, seen};
}

// In-page helpers for HyperFrames pages: mount scene files, resolve data-start, seek every composition's timeline and
// show each clip over [start, start + duration), as the HyperFrames runtime does for a render.
const PAGE_HELPERS = `(() => {
  if (window.__lfCueHelpers) return;
  const num = v => (v == null || String(v).trim() === '' ? null : Number(v));
  function localStart(el, seen) {
    const v = (el.getAttribute('data-start') || '').trim();
    if (v === '') return 0;
    if (/^-?\\d+(\\.\\d+)?$/.test(v)) return Number(v);
    const m = /^([A-Za-z_][\\w-]*)(?:\\s+([+-])\\s+(\\d+(?:\\.\\d+)?))?$/.exec(v);
    seen = seen || new Set();
    if (!m || seen.has(el)) return 0;
    const ref = document.getElementById(m[1]);
    if (!ref) return 0;
    seen.add(el);
    const base = localStart(ref, seen) + (num(ref.getAttribute('data-duration')) || 0);
    return base + (m[2] ? (m[2] === '+' ? 1 : -1) * Number(m[3]) : 0);
  }
  const parentComp = el => el.parentElement ? el.parentElement.closest('[data-composition-id]') : null;
  function compStart(el) {
    if (!el) return 0;
    return (el.hasAttribute('data-start') ? localStart(el) : 0) + compStart(parentComp(el));
  }
  function owner(el) { return el.hasAttribute('data-composition-id') ? parentComp(el) : el.closest('[data-composition-id]'); }
  function windows() {
    const rows = [];
    for (const el of document.querySelectorAll('[data-start]')) {
      const d = num(el.getAttribute('data-duration'));
      if (d == null || !Number.isFinite(d)) continue;
      const a = localStart(el) + compStart(owner(el));
      rows.push([el, a, a + d]);
    }
    return rows;
  }
  function comps() {
    const out = {};
    for (const el of document.querySelectorAll('[data-composition-id]')) {
      const id = el.getAttribute('data-composition-id');
      if (id in out) continue;
      out[id] = {start: compStart(el), duration: num(el.getAttribute('data-duration'))};
    }
    return out;
  }
  async function runScript(old, parent) {
    const s = document.createElement('script');
    for (const at of old.attributes) s.setAttribute(at.name, at.value);
    s.textContent = old.textContent;
    const loaded = s.src ? new Promise((resolve, reject) => { s.onload = resolve; s.onerror = () => reject(Error('script ' + s.src + ' did not load')); }) : null;
    parent.appendChild(s);
    if (loaded) await loaded;
  }
  async function mount() {
    for (let pass = 0; pass < 8; pass++) {
      const hosts = [...document.querySelectorAll('[data-composition-src]:not([data-lf-mounted])')];
      if (!hosts.length) return;
      for (const host of hosts) {
        host.setAttribute('data-lf-mounted', '');
        const src = host.getAttribute('data-composition-src');
        const r = await fetch(src);
        if (!r.ok) throw Error('scene file ' + src + ' could not be read (' + r.status + ')');
        const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
        const tpl = doc.querySelector('template');
        const frag = tpl ? tpl.content : doc.body;
        const scripts = [...frag.querySelectorAll('script')];
        for (const s of scripts) s.remove();
        const id = host.getAttribute('data-composition-id');
        for (const st of frag.querySelectorAll('style')) st.textContent = st.textContent.replace(/#root\\b/g, '[data-lf-scene="' + id + '"]');
        const sceneRoot = frag.querySelector('[data-composition-id]');
        if (sceneRoot) { sceneRoot.setAttribute('data-lf-scene', id); if (sceneRoot.id === 'root') sceneRoot.removeAttribute('id'); }
        for (const node of [...frag.childNodes]) host.appendChild(document.importNode(node, true));
        for (const s of scripts) await runScript(s, host);
      }
    }
  }
  let styled = false;
  function seek(t) {
    if (!styled) {
      const st = document.createElement('style');
      st.textContent = '[data-lf-hidden], [data-lf-hidden] * { visibility: hidden !important; }';
      document.head.appendChild(st); styled = true;
    }
    const c = comps();
    for (const [id, tl] of Object.entries(window.__timelines || {})) {
      if (!tl || typeof tl.seek !== 'function') continue;
      const start = c[id] ? c[id].start : 0;
      const dur = typeof tl.duration === 'function' ? tl.duration() : Infinity;
      tl.seek(Math.min(Math.max(t - start, 0), dur));
    }
    for (const [el, a, b] of windows()) el.toggleAttribute('data-lf-hidden', !(t >= a - 1e-9 && t < b - 1e-9));
  }
  function labels() {
    const c = comps(), out = [];
    for (const [id, tl] of Object.entries(window.__timelines || {})) {
      const table = tl && tl.labels ? tl.labels : {};
      for (const [name, at] of Object.entries(table)) out.push({name, at: Number(at) + (c[id] ? c[id].start : 0), composition: id});
    }
    return out;
  }
  function structure() {
    const all = [...document.querySelectorAll('[data-composition-id]')];
    const root = all.find(el => !parentComp(el)) || null;
    const missing = [...new Set(all.filter(el => !el.hasAttribute('data-no-timeline')).map(el => el.getAttribute('data-composition-id')))]
      .filter(id => !(window.__timelines && window.__timelines[id]));
    const block = document.getElementById('lf-cues');
    return {root: root && {id: root.getAttribute('data-composition-id'), duration: num(root.getAttribute('data-duration')),
                           width: num(root.getAttribute('data-width')), height: num(root.getAttribute('data-height')),
                           fps: root.getAttribute('data-fps')},
            missing, block: block ? block.textContent : null, comps: comps()};
  }
  function box(selector) {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {cx: r.left + r.width / 2, cy: r.top + r.height / 2, w: innerWidth, h: innerHeight};
  }
  function markText() {
    let n = 0;
    for (const el of document.body.querySelectorAll('*')) {
      if ([...el.childNodes].some(x => x.nodeType === 3 && x.textContent.trim())) { el.setAttribute('data-lf-text', String(n++)); }
    }
    return n;
  }
  window.__lfCueHelpers = {mount, seek, labels, structure, box, markText};
})()`;

async function settle(page) {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function seekPage(page, kind, t) {
  await within(page.evaluate(({kind, t}) => {
    if (kind === 'lf') { if (typeof window.__lf.frame === 'function') window.__lf.frame(t); window.__lf.seek(t); }
    else window.__lfCueHelpers.seek(t);
  }, {kind, t}), FRAME_MS, `seeking t=${t}`);
  await settle(page);
}

function changedFraction(a, b) {
  if (a.w !== b.w || a.h !== b.h) return 1;
  let changed = 0;
  const n = a.w * a.h;
  for (let i = 0; i < n; i++) {
    const p = i * a.channels, q = i * b.channels;
    const d = Math.max(Math.abs(a.out[p] - b.out[q]), Math.abs(a.out[p+1] - b.out[q+1]), Math.abs(a.out[p+2] - b.out[q+2]));
    if (d > 8) changed++;
  }
  return changed / n;
}
const NO_CHANGE = 1e-5;   // fewer than 1 pixel in 100,000 moved by more than 8 levels: the frame held

async function capture(page) {
  return pngDecode(await page.screenshot({type: 'png', scale: 'css', timeout: FRAME_MS}));
}

function rel(from, to) {
  const r = path.relative(path.dirname(from), to);
  if (!r || path.isAbsolute(r)) return to.split(path.sep).join('/') + '/';
  return (r.split(path.sep).join('/') || '.') + '/';
}

function writeAtomic(file, text) {
  fs.mkdirSync(path.dirname(file), {recursive: true});
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text, 'utf8');
  fs.renameSync(tmp, file);
}

function pick(entry) {
  const ev = {}, extra = {};
  for (const [k, v] of Object.entries(entry)) {
    if (k === 'el') continue;
    if (EVENT_KEYS.includes(k)) ev[k] = v; else extra[k] = v;
  }
  return [ev, extra];
}

function checkEvent(ev, problems) {
  const name = ev.id;
  if (!SCALES.has(ev.scale)) problems.push(`event ${name}: unknown scale ${JSON.stringify(ev.scale)}`);
  if (ev.sync != null && !SYNCS.has(ev.sync)) problems.push(`event ${name}: unknown sync ${JSON.stringify(ev.sync)}`);
  if (ev.sound != null && !SOUNDS.has(ev.sound)) problems.push(`event ${name}: unknown sound ${JSON.stringify(ev.sound)}`);
  if (!Number.isFinite(ev.t) || ev.t < 0) problems.push(`event ${name}: no time`);
  if (SPANS.has(ev.scale) && !(Number.isFinite(ev.t_end) && ev.t_end > ev.t)) problems.push(`event ${name}: a ${ev.scale} span needs an end after its start`);
  if (ev.scale === 'silence') {
    if (!SCOPES.has(ev.scope)) problems.push(`event ${name}: silence needs scope new, effects or all`);
    if (!ev.decision) problems.push(`event ${name}: silence needs a decision`);
  }
  if (ev.picture === 'held' && !ev.decision) problems.push(`event ${name}: picture: held needs a decision (a frame that holds on purpose)`);
  for (const k of ['x', 'y']) if (ev[k] != null && !(Number.isFinite(ev[k]) && ev[k] >= -1 && ev[k] <= 1)) problems.push(`event ${name}: ${k} must be -1..1`);
  if (ev.lead_ms != null && !Number.isFinite(ev.lead_ms)) problems.push(`event ${name}: lead_ms must be a number`);
}

// Labels give time; the lf-cues block gives meaning; merged by id, nothing guessed.
function fromTimelines(struct, labels, fps, problems) {
  let block;
  try { block = JSON.parse(struct.block); } catch (e) { problems.push(`the lf-cues block is not JSON: ${e.message}`); return {sections: [], events: []}; }
  const secDecl = block.sections || {}, evDecl = block.events || {};
  const table = new Map();
  for (const l of labels) {
    if (!/^(cue|section):/.test(l.name)) continue;
    if (table.has(l.name)) { problems.push(`label ${l.name} appears in two compositions (${table.get(l.name).composition}, ${l.composition})`); continue; }
    table.set(l.name, l);
  }
  const at = name => (table.has(name) ? Math.round(table.get(name).at * 1e6) / 1e6 : null);
  const duration = struct.root && struct.root.duration;
  // Sections: start labels in time order; each ends at its own :end label or the next start.
  const starts = [...table.keys()].filter(n => /^section:[^:]+$/.test(n)).map(n => n.slice(8));
  for (const id of starts) if (!(id in secDecl)) problems.push(`label section:${id} has no entry in the lf-cues block`);
  for (const id of Object.keys(secDecl)) if (!table.has(`section:${id}`)) problems.push(`section ${id} in the lf-cues block has no section:${id} label`);
  for (const n of table.keys()) { const m = /^section:([^:]+):end$/.exec(n); if (m && !table.has(`section:${m[1]}`)) problems.push(`label ${n} has no section:${m[1]} start`); }
  const ordered = starts.filter(id => id in secDecl).sort((x, y) => at(`section:${x}`) - at(`section:${y}`));
  const sections = ordered.map((id, i) => {
    const a = at(`section:${id}`), next = i + 1 < ordered.length ? at(`section:${ordered[i+1]}`) : duration;
    const end = at(`section:${id}:end`);
    const b = end != null ? end : next;
    const d = secDecl[id] || {};
    if (!CLOCKS.has(d.clock)) problems.push(`section ${id}: clock must be speech, music, action or silence`);
    if (!(Number.isFinite(b) && b > a)) problems.push(`section ${id}: its end is not after its start`);
    if (end != null && i + 1 < ordered.length && end > next + 1e-6) problems.push(`section ${id} ends at ${end} s, after ${ordered[i+1]} starts at ${next} s`);
    const row = {id, a, b, clock: d.clock};
    for (const k of ['label', 'decision', 'gain_db']) if (d[k] != null) row[k] = d[k];
    return row;
  });
  if (!sections.length) problems.push('the page declares no sections: label section:<id> on a timeline and give each a clock in the lf-cues block');
  const cueIds = [...table.keys()].filter(n => /^cue:[^:]+$/.test(n)).map(n => n.slice(4));
  for (const id of cueIds) if (!(id in evDecl)) problems.push(`label cue:${id} has no entry in the lf-cues block`);
  for (const n of table.keys()) { const m = /^cue:([^:]+):end$/.exec(n); if (m && !table.has(`cue:${m[1]}`)) problems.push(`label ${n} has no cue:${m[1]} start`); }
  const events = [];
  for (const [id, entry] of Object.entries(evDecl)) {
    if (!table.has(`cue:${id}`)) { problems.push(`event ${id} in the lf-cues block has no cue:${id} label`); continue; }
    if (entry.t != null || entry.t_end != null) problems.push(`event ${id}: time comes from its labels, not the block`);
    const [ev, extra] = pick({scale: 'contact', ...entry});
    ev.id = id; ev.t = at(`cue:${id}`);
    const end = at(`cue:${id}:end`);
    if (end != null) ev.t_end = end;
    if (SPANS.has(ev.scale) && end == null) problems.push(`event ${id}: a ${ev.scale} span needs a cue:${id}:end label`);
    if (Object.keys(extra).length) ev.declared = extra;
    events.push({ev, el: entry.el});
  }
  return {sections, events};
}

function fromList(list, labels, kind, problems) {
  if (!Array.isArray(list)) { problems.push(`the ${kind} cue list is not an array`); return []; }
  const table = new Map(labels.map(l => [l.name, l.at]));
  const used = new Set(), out = [];
  list.forEach((entry, i) => {
    if (!entry || typeof entry !== 'object') { problems.push(`${kind} cue ${i + 1} is not an object`); return; }
    const [ev, extra] = pick({...entry});
    if (ev.role == null && typeof entry.type === 'string') { ev.role = entry.type; delete extra.type; }
    for (const k of ['x', 'y']) if (ev[k] != null && !(Number.isFinite(ev[k]) && ev[k] >= -1 && ev[k] <= 1)) { extra[k] = ev[k]; delete ev[k]; }
    if (ev.t == null && ev.label != null) {
      const name = String(ev.label);
      const found = table.has(name) ? table.get(name) : table.has(`cue:${name}`) ? table.get(`cue:${name}`) : null;
      if (found == null) problems.push(`${kind} cue ${ev.id ?? i + 1}: label ${name} is on no timeline`);
      else ev.t = Math.round(found * 1e6) / 1e6;
    }
    let id = ev.id != null ? String(ev.id) : `${ev.role || 'cue'}-${i + 1}`;
    for (let k = 2; used.has(id); k++) id = `${ev.id ?? ev.role ?? 'cue'}-${k}`;
    used.add(id); ev.id = id;
    if (ev.scale == null) ev.scale = 'contact';
    // A v1 silent cue's window_ms becomes a silence span; v2 has no window_ms.
    if (ev.window_ms != null || extra.window_ms != null) {
      const w = Number(extra.window_ms ?? ev.window_ms) / 1000; delete extra.window_ms;
      if (ev.sound === 'silent' && Number.isFinite(w) && w > 0) {
        Object.assign(ev, {scale: 'silence', t: Math.max(0, ev.t - w), t_end: ev.t + w, scope: ev.scope || 'new',
                           decision: ev.decision || `declared silent: ${entry.picture || id}`});
      }
    }
    if (Object.keys(extra).length) ev.declared = extra;
    out.push({ev, el: entry.el});
  });
  return out;
}

function placeInSections(events, sections, fps, problems) {
  if (!sections.length) return;
  const last = sections[sections.length - 1];
  for (const {ev} of events) {
    const sec = sections.find(s => ev.t >= s.a - 1e-6 && ev.t < s.b - 1e-6) || (Math.abs(ev.t - last.b) <= 1e-6 ? last : null);
    if (!sec) { problems.push(`event ${ev.id} at ${ev.t} s is outside every section`); continue; }
    if (ev.section != null && ev.section !== sec.id) problems.push(`event ${ev.id} names section ${ev.section} but sits in ${sec.id}`);
    ev.section = sec.id;
  }
  const frame = 1 / fps;
  sections.forEach((s, i) => {
    if (i === 0 || s.decision) return;
    const turn = events.some(({ev}) => ev.scale === 'turn' && Math.abs(ev.t - s.a) <= frame + 1e-6);
    if (!turn) problems.push(`section ${s.id} starts a turn at ${s.a} s: declare a turn event there or a decision on the section`);
  });
}

function orderEvent(ev) {
  const out = {};
  for (const k of EVENT_KEYS) if (ev[k] !== undefined) out[k] = ev[k];
  if (ev.declared) out.declared = ev.declared;
  return out;
}

async function systemFonts(page) {
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
    const count = await page.evaluate(() => window.__lfCueHelpers ? window.__lfCueHelpers.markText() : (() => {
      let n = 0; for (const el of document.body.querySelectorAll('*'))
        if ([...el.childNodes].some(x => x.nodeType === 3 && x.textContent.trim())) el.setAttribute('data-lf-text', String(n++));
      return n; })());
    if (!count) return {custom: [], system: []};
    const {root} = await cdp.send('DOM.getDocument', {depth: 0});
    const {nodeIds} = await cdp.send('DOM.querySelectorAll', {nodeId: root.nodeId, selector: '[data-lf-text]'});
    const custom = new Set(), system = new Map();
    for (const nodeId of nodeIds.slice(0, 4000)) {
      let fonts;
      try { ({fonts} = await cdp.send('CSS.getPlatformFontsForNode', {nodeId})); } catch { continue; }
      for (const f of fonts || []) {
        if (!f.glyphCount) continue;
        if (f.isCustomFont) custom.add(f.familyName);
        else if (!system.has(f.familyName)) {
          const {outerHTML} = await cdp.send('DOM.getOuterHTML', {nodeId}).catch(() => ({outerHTML: ''}));
          system.set(f.familyName, outerHTML.slice(0, 80));
        }
      }
    }
    await page.evaluate(() => { for (const el of document.querySelectorAll('[data-lf-text]')) el.removeAttribute('data-lf-text'); });
    return {custom: [...custom].sort(), system: [...system.entries()].map(([family, where]) => ({family, where}))};
  } finally { await cdp.detach().catch(() => {}); }
}

async function cuesMain(argv) {
  let a;
  try { a = cueArgs(argv); } catch (e) { console.error(`film_capture.mjs cues: ${e.message}`); return 2; }
  if (a.help || !a.target) { console.log(CUE_HELP); return a.help ? 0 : 2; }
  let browser, srv;
  try {
    if (!a.out) throw refuse('--out cues.json is required');
    if (a.source && !['lf', 'declared', 'timelines'].includes(a.source)) throw refuse('--source must be lf, declared or timelines');
    let pageDir, entry = 'index.html';
    if (/^https?:/i.test(a.target)) {
      if (!a.root) throw refuse('a URL needs --root DIR, the folder it serves, so the list can record the page identity');
      const u = new URL(a.target);
      entry = (u.pathname.replace(/^\/+/, '') || 'index.html') + u.search;
      pageDir = path.resolve(a.root);
    } else pageDir = path.resolve(a.target);
    if (!fs.existsSync(pageDir) || !fs.statSync(pageDir).isDirectory()) throw refuse(`${pageDir} is not a page folder`);
    if (!fs.existsSync(path.join(pageDir, entry.split('?')[0]))) throw refuse(`${pageDir} has no ${entry.split('?')[0]}`);
    const out = path.resolve(a.out);
    refuseOutput(out, [pageDir, path.join(pageDir, entry.split('?')[0])], pageDir);
    const requested = a.size ? /^(\d+)[xX](\d+)$/.exec(a.size) : null;
    if (a.size && !requested) throw refuse('--size must be WxH');
    const fpsGiven = a.fps != null ? fpsValue(a.fps) : null;

    const frozen = freezePage(pageDir, a, entry.split('?')[0]);
    const copy = path.resolve(pageDir, frozen.copy);
    const relOut = path.relative(pageDir, out).split(path.sep).join('/');
    if (frozen.source_files && Object.prototype.hasOwnProperty.call(frozen.source_files, relOut))
      throw refuse(`the output ${out} is a page file the fingerprint covers; write the list elsewhere`);
    srv = await serveFolder(copy);
    const loaded = await playwright(a), pw = loaded.api, exe = browserPath(pw, a);
    browser = await pw.chromium.launch({executablePath: exe, headless: true, args: ['--force-color-profile=srgb',
      '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--run-all-compositor-stages-before-draw',
      '--font-render-hinting=none']});
    activeBrowser = browser;
    const viewport = requested ? {width: Number(requested[1]), height: Number(requested[2])} : {width: 1920, height: 1080};
    const context = await browser.newContext({viewport, deviceScaleFactor: 1, serviceWorkers: 'block'});
    const left = [], errors = [];
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      // A request that leaves the copy is let through and recorded: the page still exports, bound unverified.
      if (u.origin !== srv.origin) left.push(route.request().url());
      await route.continue();
    });
    await context.addInitScript(() => { window.__timelines = window.__timelines || {}; });
    const page = await context.newPage();
    page.on('websocket', ws => left.push(ws.url()));
    page.on('pageerror', e => errors.push(`page error: ${e.message}`));
    await within(page.goto(`${srv.origin}/${entry}`, {waitUntil: 'load', timeout: READY_MS}), READY_MS + 1000, 'loading the page');
    await page.addScriptTag({content: PAGE_HELPERS});
    const has = await page.evaluate(({global}) => ({lf: !!window.__lf, block: !!document.getElementById('lf-cues'),
      declared: Array.isArray(window[global])}), {global: a.global || '__cues'});
    const kind = a.source || (has.block ? 'timelines' : has.lf ? 'lf' : 'declared');
    const notReady = () => {
      const missing = [...new Set(srv.seen.filter(r => r.status !== 200).map(r => r.path))];
      return (missing.length ? `; the copy does not hold ${missing.slice(0, 6).join(', ')}` : '') +
        (errors.length ? `; ${errors.slice(0, 3).join('; ')}` : '');
    };
    const problems = [];
    let fps, duration, width = viewport.width, height = viewport.height, sections = [], events = [], seekKind = 'timelines';
    if (kind === 'lf') {
      try { await page.waitForFunction(() => !!window.__lf, {}, {timeout: 30000}); }
      catch (e) { throw refuse('window.__lf did not appear within 30 s' + notReady()); }
      await within(page.evaluate(async () => { await window.__lf.ready; await document.fonts.ready; }), READY_MS, 'window.__lf.ready');
      const info = await page.evaluate(() => window.__lf.info());
      validate(info);
      fps = fpsGiven || {value: info.fps, stored: info.fps};
      duration = info.duration; width = info.width; height = info.height; seekKind = 'lf';
      if (!requested) await page.setViewportSize({width, height});
      sections = Array.isArray(info.sections) ? info.sections : [];
      events = fromList(info.cues || [], [], 'kit', problems);
    } else {
      if (kind === 'timelines') {
        await within(page.evaluate(() => window.__lfCueHelpers.mount()), READY_MS, 'mounting scene files');
      } else {
        const flag = a.ready || '__cues_ready';
        try { await page.waitForFunction(f => window[f] === true, flag, {timeout: READY_MS, polling: 100}); }
        catch (e) { throw refuse(`the page did not set window.${flag} = true within ${READY_MS / 1000} s (--ready names another flag)` + notReady()); }
      }
      await within(page.evaluate(() => document.fonts.ready), READY_MS, 'the page fonts');
      if (kind === 'timelines') {
        const start = Date.now();
        for (;;) {
          const missing = await page.evaluate(() => window.__lfCueHelpers.structure().missing);
          if (!missing.length) break;
          if (Date.now() - start > READY_MS) throw refuse(`composition(s) ${missing.join(', ')} registered no timeline in window.__timelines`);
          await new Promise(r => setTimeout(r, 100));
        }
      }
      const struct = await page.evaluate(() => window.__lfCueHelpers.structure());
      const labels = await page.evaluate(() => window.__lfCueHelpers.labels());
      const root = struct.root || {};
      fps = fpsGiven || fpsValue(root.fps || null) || {value: 30, stored: 30};
      duration = root.duration;
      if (root.width && root.height) { width = root.width; height = root.height; }
      if (!requested && root.width && root.height) await page.setViewportSize({width, height});
      if (kind === 'timelines') {
        if (struct.block == null) throw refuse('the page has no <script type="application/json" id="lf-cues"> block');
        ({sections, events} = fromTimelines(struct, labels, fps.value, problems));
      } else {
        const list = await page.evaluate(g => JSON.parse(JSON.stringify(window[g])), a.global || '__cues');
        events = fromList(list, labels, 'declared', problems);
        const lf = await page.evaluate(() => !!window.__lf);
        if (lf && !Object.keys(struct.comps).length) seekKind = 'lf';
        if (!duration && lf) duration = (await page.evaluate(() => window.__lf.info())).duration;
        if (!fpsGiven && lf) { const f = (await page.evaluate(() => window.__lf.info())).fps; fps = {value: f, stored: f}; }
      }
    }
    const ids = new Set();
    for (const {ev} of events) { if (ids.has(ev.id)) problems.push(`event id ${ev.id} is used twice`); ids.add(ev.id); checkEvent(ev, problems); }
    placeInSections(events, sections, fps.value, problems);
    if (errors.length) problems.push(...errors);
    if (problems.length) throw refuse('the declaration is incomplete or inconsistent:\n  ' + [...new Set(problems)].join('\n  '));
    const canSeek = seekKind === 'lf' || await page.evaluate(() => Object.keys(window.__timelines || {}).length > 0);
    // el gives x, y from the element's box at t.
    for (const row of events) {
      if (!row.el) continue;
      if (!canSeek) throw refuse(`event ${row.ev.id}: el needs a page that seeks (window.__lf or window.__timelines)`);
      await seekPage(page, seekKind, row.ev.t);
      const b = await page.evaluate(sel => window.__lfCueHelpers.box(sel), row.el);
      if (!b) throw refuse(`event ${row.ev.id}: el ${row.el} matches nothing at ${row.ev.t} s`);
      row.ev.x = Math.round(Math.max(-1, Math.min(1, 2 * b.cx / b.w - 1)) * 1e4) / 1e4;
      row.ev.y = Math.round(Math.max(-1, Math.min(1, 2 * b.cy / b.h - 1)) * 1e4) / 1e4;
    }
    let verify = null, looks = 0;
    if (a.verify) {
      if (!canSeek) throw refuse('--verify needs a page that seeks (window.__lf or window.__timelines)');
      verify = {method: 't-1f, t, t+1f; a change is more than 1 pixel in 100,000 moving by more than 8 levels', probed: [], flagged: [], skipped: []};
      const cache = new Map();
      const frameAt = async k => {
        if (!cache.has(k)) { await seekPage(page, seekKind, Math.max(0, k) / fps.value); cache.set(k, await capture(page)); }
        return cache.get(k);
      };
      for (const {ev} of [...events].sort((x, y) => x.ev.t - y.ev.t)) {
        if (!['turn', 'contact'].includes(ev.scale)) continue;
        if (ev.picture === 'none' || ev.picture === 'held') { verify.skipped.push({id: ev.id, t: ev.t, picture: ev.picture, ...(ev.decision ? {decision: ev.decision} : {})}); continue; }
        const k = Math.round(ev.t * fps.value);
        const before = changedFraction(await frameAt(k - 1), await frameAt(k)), after = changedFraction(await frameAt(k), await frameAt(k + 1));
        const row = {id: ev.id, t: ev.t, scale: ev.scale, frame: k, changed_into: Number(before.toFixed(6)), changed_out: Number(after.toFixed(6))};
        verify.probed.push(row);
        if (before <= NO_CHANGE && after <= NO_CHANGE) { verify.flagged.push({...row, look: 'no frame change'}); looks++; }
        if (cache.size > 12) cache.delete(cache.keys().next().value);
      }
    }
    let candidates = null, candidatesScan = null;
    if (a.candidates) {
      if (!canSeek) throw refuse('--candidates needs a page that seeks (window.__lf or window.__timelines)');
      if (!(Number.isFinite(duration) && duration > 0))
        throw refuse('--candidates needs the film\'s duration (the root composition\'s data-duration, or __lf.info().duration)');
      // Samples lie inside the film, [0, duration): at t = duration every clip has ended and the picture blanks.
      const rate = Math.min(fps.value, 30), n = Math.ceil(duration * rate - 1e-9) - 1;
      if (n < 2) throw refuse(`--candidates needs at least three samples; a ${duration} s film at ${rate} samples a second has ${n + 1}`);
      const diffs = [];
      let prev = null;
      for (let k = 0; k <= n; k++) {
        const t = k / rate;
        let img;
        try { await seekPage(page, seekKind, t); img = await capture(page); }
        catch (e) {
          // A failed sample is never an empty result: the scan stops, says which sample, and writes no list.
          throw refuse(`--candidates: the seek or capture of sample ${k + 1} of ${n + 1} at ${t.toFixed(3)} s failed, so no ` +
                       `candidate list was written: ${String(e.message).split('\n')[0]}`);
        }
        if (prev) diffs.push({t: Math.round(t * 1e6) / 1e6, d: changedFraction(prev, img)});
        prev = img;
      }
      const half = Math.max(1, Math.round(rate / 2));
      candidates = diffs.filter((x, i) => {
        const near = diffs.slice(Math.max(0, i - half), i + half + 1).map(y => y.d).sort((p, q) => p - q);
        const median = near[Math.floor(near.length / 2)];
        return x.d > NO_CHANGE && x.d > 3 * median && x.d >= (diffs[i - 1]?.d ?? 0) && x.d >= (diffs[i + 1]?.d ?? 0);
      }).map(x => ({t: x.t, score: Number(x.d.toFixed(6)), state: 'unconfirmed'}));
      const max = Math.max(...diffs.map(x => x.d));
      candidatesScan = {samples: n + 1, rate: Math.round(rate * 1e6) / 1e6, max_change: Number(max.toFixed(6)),
        state: max <= NO_CHANGE ? 'inconclusive' : candidates.length ? 'found' : 'none',
        ...(max <= NO_CHANGE ? {reason: 'every sample matched the one before it: nothing moved, or the capture did not paint'} :
            candidates.length ? {} : {reason: 'the picture moves, but no change stands out from its surrounding second'})};
      if (candidatesScan.state === 'inconclusive') looks++;
    }
    if (canSeek) await seekPage(page, seekKind, 0);
    const fonts = await systemFonts(page);
    if (seekKind === 'lf') await page.evaluate(() => { if (typeof window.__lf.frame === 'function') window.__lf.frame(null); });
    await context.close();
    const missing = srv.seen.filter(r => r.status !== 200).map(r => r.path);
    const pageFiles = new Set(Object.keys(frozen.source_files || {}));
    const loadedFiles = [...new Set(srv.seen.filter(r => r.status === 200).map(r => r.path.replace(/^\/+/, '')))]
      .filter(rel => pageFiles.has(rel));
    const scannedStatic = new Set(frozen.scanned || [...pageFiles]);
    const atExport = scanLoaded(pageDir, loadedFiles.filter(rel => !scannedStatic.has(rel)), a);
    const unreached = (frozen.not_scanned || []).filter(rel => !loadedFiles.includes(rel));
    const reasons = [...(frozen.reasons || []), ...(atExport.reasons || [])];
    for (const u of left) reasons.push(`request left the copy: ${u}`);
    for (const p of missing) reasons.push(`request the copy does not hold: ${p}`);
    for (const f of fonts.system) reasons.push(`system font ${f.family} draws text (${f.where})`);
    const binding = reasons.length ? 'unverified' : 'closed';
    const list = {
      version: 'v2', clock: 'seconds from the first frame of the film', fps: fps.stored,
      exported_from: `film_capture.mjs cues --source ${kind}`, provenance: 'exported',
      picture: {kind: 'page', path: rel(out, pageDir), sha256: frozen.fingerprint, snapshot_sha256: frozen.snapshot_sha256,
                source_files: frozen.source_files},
      binding, ...(reasons.length ? {binding_reasons: [...new Set(reasons)]} : {}),
      sections, events: events.map(r => orderEvent(r.ev)).sort((x, y) => x.t - y.t || String(x.id).localeCompare(String(y.id))),
      export: {entry, size: `${width}x${height}`, ...(duration != null ? {duration} : {}), frozen: path.relative(pageDir, copy).split(path.sep).join('/'),
               scanned: {static: [...scannedStatic].length, at_export: atExport.files || []},
               not_loaded_not_scanned: unreached,
               requests: srv.seen, left_copy: left, fonts, browser: browser.version(), playwright: loaded.version,
               ...(verify ? {verify} : {}), ...(candidates ? {candidates, candidates_scan: candidatesScan} : {})},
    };
    writeAtomic(out, JSON.stringify(list, null, 1) + '\n');
    const by = s => list.events.filter(e => e.scale === s).length;
    console.log(`${path.basename(out)}: ${list.events.length} events (${by('turn')} turns, ${by('follow')} follow, ${by('contact')} contacts, ` +
      `${by('silence')} silences), ${sections.length} sections, from ${kind}; fingerprint ${String(frozen.fingerprint).slice(0, 12)}, ` +
      `snapshot ${String(frozen.snapshot_sha256).slice(0, 12)}; binding ${binding}`);
    for (const r of list.binding_reasons || []) console.log(`  unverified: ${r.length > 300 ? r.slice(0, 300) + ` ... (${r.length} characters; all in the list)` : r}`);
    if (unreached.length) console.log(`  not loaded, not scanned: ${unreached.length} file(s), copied and fingerprinted` +
      ` (${unreached.slice(0, 3).join(', ')}${unreached.length > 3 ? ', ...' : ''})`);
    if (verify) {
      console.log(`  verify: ${verify.probed.length} probed, ${verify.flagged.length} with no frame change` + (verify.skipped.length ? `, ${verify.skipped.length} skipped (picture none or held)` : ''));
      for (const f of verify.flagged) console.log(`  look: no frame change at ${f.id} (${f.scale}, ${f.t} s, frame ${f.frame})`);
      for (const s of verify.skipped) console.log(`  listed: ${s.id} at ${s.t} s, picture: ${s.picture}${s.decision ? `; ${s.decision}` : ''}`);
    }
    if (candidates) {
      const scan = candidatesScan;
      console.log(scan.state === 'inconclusive'
        ? `  look: candidates inconclusive: ${scan.reason} (${scan.samples} samples)`
        : `  candidates: ${candidates.length} motion peaks, unconfirmed (${scan.samples} samples at ${scan.rate} a second, ` +
          `largest change ${scan.max_change}${scan.reason ? `; ${scan.reason}` : ''})`);
    }
    return looks ? 1 : 0;
  } catch (e) {
    console.error(`film_capture.mjs cues: ${e.message}`);
    return 2;
  } finally {
    if (browser) { await browser.close().catch(() => {}); activeBrowser = undefined; }
    if (srv) srv.server.close();
  }
}

export {cuesMain, fromTimelines, fromList, placeInSections, refuseOutput, changedFraction};

// Exporting the scheduler permits cross-language contract tests without launching Chromium.
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  main().catch(e=>{console.error(`film_capture.mjs: ${e.message}`);process.exitCode=2;});
}
