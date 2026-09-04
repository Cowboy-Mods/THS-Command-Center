const {chromium}=require('playwright');
const sharp=require('sharp');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const root=path.resolve(__dirname,'../ui'),out=path.resolve(__dirname,'../evidence/halo-layer-20260903');
const server=http.createServer((req,res)=>{const file=path.resolve(root,'.'+(new URL(req.url,'http://localhost').pathname==='/'?'/index.html':new URL(req.url,'http://localhost').pathname));if(!file.startsWith(root+path.sep)){res.writeHead(403);return res.end();}try{res.setHeader('Content-Type',({'.html':'text/html','.css':'text/css','.js':'text/javascript','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;try{
 fs.mkdirSync(out,{recursive:true});const origin=`http://127.0.0.1:${server.address().port}`;browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const context=await browser.newContext({reducedMotion:'reduce'});let forbidden=0;await context.route('**/*',r=>{if(!r.request().url().startsWith(origin+'/')||r.request().url().includes('/api/')){forbidden++;return r.abort();}return r.continue();});await context.addInitScript(()=>{window.forbidden=0;const deny=()=>{window.forbidden++;throw Error('Forbidden audio');};navigator.mediaDevices.getUserMedia=deny;window.AudioContext=deny;HTMLMediaElement.prototype.play=deny;});const page=await context.newPage();let checks=0;
 for(const [width,height] of [[2560,1440],[1920,1080],[430,932],[393,852],[932,430]]){
 await page.setViewportSize({width,height});for(const id of ['focus','maeve','addie','maddie','callie','isla','junior-bub','oliver','aiden','shop-ops']){
 await page.goto(origin+(id==='focus'?'/?focus=conversation':'/?specialist='+id));await page.waitForLoadState('networkidle');await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode().catch(()=>{}))));
 const halo=page.locator(id==='focus'?'.halo-wrap':'.specialist-static-halo');const portrait=page.locator(id==='focus'?'.maeve-focus-portrait':'#specialist-portrait');
 const h=await halo.evaluate(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return{x:r.x,y:r.y,w:r.width,h:r.height,z:+s.zIndex,pointer:s.pointerEvents,mask:s.maskImage};});assert(h.z>await portrait.evaluate(e=>+getComputedStyle(e).zIndex));assert.equal(h.pointer,'none');assert(h.mask.includes('75%'));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));if(id!=='focus')assert.equal(await page.locator('.specialist-voice-controls button:disabled').count(),4);
 // Raster comparison proves the overlay actually contributes visible pixels.
 async function stable(){let previous;for(let i=0;i<10;i++){const next=await page.screenshot({animations:'disabled'});if(previous?.equals(next))return next;previous=next;}throw Error('Unstable raster');}
 const actual=await stable();
 // Isolate the overlay raster from Edge's independent high-resolution image
 // compositing. Portrait stays unchanged in production and in review captures.
 await portrait.evaluate(e=>e.style.visibility='hidden');
 const before=await stable();await halo.evaluate(e=>{e.style.maskImage='linear-gradient(transparent,transparent)';e.style.webkitMaskImage='linear-gradient(transparent,transparent)';});const hidden=await stable();await halo.evaluate(e=>{e.style.removeProperty('mask-image');e.style.removeProperty('-webkit-mask-image');});await portrait.evaluate(e=>e.style.removeProperty('visibility'));
 const a=await sharp(before).ensureAlpha().raw().toBuffer(),b=await sharp(hidden).ensureAlpha().raw().toBuffer();let changed=0,central=0;for(let y=0;y<height;y++)for(let x=0;x<width;x++){const p=(y*width+x)*4;if(Math.abs(a[p]-b[p])+Math.abs(a[p+1]-b[p+1])+Math.abs(a[p+2]-b[p+2])>8){changed++;if(x>h.x+h.w*.26&&x<h.x+h.w*.74)central++;}}assert(changed>10,`${id} halo invisible at ${width}`);assert.equal(central,0,`${id} halo crosses central face-safe region`);assert.equal(await page.evaluate(()=>window.forbidden),0);checks++;
 if(['focus','oliver','addie','shop-ops'].includes(id))fs.writeFileSync(path.join(out,`${id}-${width}x${height}.png`),actual);
 }}assert.equal(forbidden,0);console.log(JSON.stringify({focusedViews:checks,visibleHalo:true,centralFaceRegionClear:true,noninteractive:true,forbiddenCalls:0}));
 }finally{if(browser)await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1});
