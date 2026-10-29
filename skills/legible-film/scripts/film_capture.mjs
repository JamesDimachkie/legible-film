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
  for (const root of [path.join(process.cwd(), 'package.json'), fileURLToPath(import.meta.url)]) {
    const req = createRequire(root);
    for (const name of ['playwright', 'playwright-core']) {
      try { return load(req,name); } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
    }
  }
  throw Error('Playwright missing: npm install playwright-core, or --playwright PATH');
}
function browserPath(pw, a) {
  const explicit = a.browser || process.env.LF_CHROMIUM;
  if (explicit) { if (!fs.existsSync(explicit)) throw Error('Chromium executable missing'); return explicit; }
  if (fs.existsSync(pw.chromium.executablePath())) return pw.chromium.executablePath();
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), '.cache'), 'ms-playwright');
  const builds = fs.existsSync(cache) ? fs.readdirSync(cache).filter(x => /^chromium-\d+$/.test(x))
    .sort((a,b) => Number(b.split('-')[1]) - Number(a.split('-')[1])) : [];
  for (const build of builds) for (const exe of ['chrome-win64/chrome.exe','chrome-win/chrome.exe','chrome-linux/chrome','chrome-mac/Chromium.app/Contents/MacOS/Chromium']) {
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
async function paint(page, t, frame) {
  await page.evaluate(async ({t, frame}) => {
    if (frame !== undefined) window.__lf.frame(frame);
    window.__lf.seek(t);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  }, {t, frame});
}
function pngPixels(buf) {
  let pos = 8, w, h, channels, compressed = [];
  while (pos < buf.length) {
    const size = buf.readUInt32BE(pos), type = buf.toString('ascii',pos+4,pos+8), data = buf.subarray(pos+8,pos+8+size);
    if (type === 'IHDR') { w=data.readUInt32BE(0); h=data.readUInt32BE(4); channels = data[9] === 6 ? 4 : data[9] === 2 ? 3 : 0; if(data[8]!==8 || !channels) throw Error('unsupported calibration PNG'); }
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
  return {w,h,pixel:(x,y)=>Array.from(out.subarray(y*stride+x*channels,y*stride+x*channels+3))};
}
const CAL = `<!doctype html><style>*{box-sizing:border-box}html,body{margin:0;width:320px;height:180px;background:#263544;overflow:hidden}#border{position:absolute;inset:0;border:1px solid white;z-index:4}.mark{position:absolute;width:8px;height:8px;z-index:5}.layer{position:absolute;left:20px;top:20px;width:280px;height:140px;background:#00cc66;transform:perspective(900px) rotateY(.01deg);will-change:transform}#type{position:absolute;left:60px;top:70px;font:20px Arial;color:white;z-index:3}</style><div class=layer id=layer></div><div id=type>FONTS READY</div><div id=border></div><div class=mark style="left:1px;top:1px;background:red"></div><div class=mark style="right:1px;top:1px;background:lime"></div><div class=mark style="left:1px;bottom:1px;background:blue"></div><div class=mark style="right:1px;bottom:1px;background:yellow"></div><script>window.__lf={ready:document.fonts.ready,info:()=>({width:320,height:180,fps:60,duration:1,frames:60,cuts:[]}),frame:()=>{},seek:t=>{document.querySelector('#layer').style.transform='perspective(900px) rotateY(.01deg) translateX('+(t*2)+'px)'}};</script>`;

async function main() {
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
    await page.evaluate(async()=>{await window.__lf.ready; await document.fonts.ready;});
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
// Exporting the scheduler permits cross-language contract tests without launching Chromium.
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  main().catch(e=>{console.error(`film_capture.mjs: ${e.message}`);process.exitCode=2;});
}
