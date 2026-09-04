const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const root=path.resolve(__dirname,'../ui'),out=path.resolve(__dirname,'../evidence/desktop-readability-20260903');
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.webmanifest':'application/manifest+json'};
const server=http.createServer((req,res)=>{const target=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname==='/'?'/index.html':new URL(req.url,'http://localhost').pathname));if(!target.startsWith(root+path.sep)){res.writeHead(403);return res.end();}try{res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');res.end(fs.readFileSync(target));}catch{res.writeHead(404);res.end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;try{
  fs.mkdirSync(out,{recursive:true});const origin=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const context=await browser.newContext({reducedMotion:'reduce'});let external=0;
  await context.route('**/*',route=>{if(!route.request().url().startsWith(origin+'/')){external++;return route.abort();}return route.continue();});
  await context.addInitScript(()=>{window.forbiddenCalls=0;const deny=()=>{window.forbiddenCalls++;throw new Error('Audio forbidden in visual QA');};navigator.mediaDevices.getUserMedia=deny;window.AudioContext=deny;window.webkitAudioContext=deny;});
  const page=await context.newPage(),results=[];
  async function ready(url){await page.goto(origin+url);await page.waitForLoadState('networkidle');await page.evaluate(()=>Promise.all([...document.images].map(i=>i.decode().catch(()=>{}))));}
  for(const [width,height] of [[2560,1440],[1920,1080],[1280,720]]){
    await page.setViewportSize({width,height});
    for(const [name,url] of [['home','/'],['focus','/?focus=conversation'],['crew','/?view=crew']]){
      await ready(url);if(name==='crew')await page.getByRole('button',{name:'Open MAEVE, COMMANDER details',exact:true}).click();
      const metrics=await page.evaluate(()=>{const r=s=>{const e=document.querySelector(s),b=e.getBoundingClientRect();return{x:b.x,y:b.y,right:b.right,bottom:b.bottom,width:b.width,height:b.height,font:getComputedStyle(e).fontSize}};return{overflow:document.documentElement.scrollWidth>innerWidth,mic:window.forbiddenCalls,wave:r('.voice-display'),portrait:r('.maeve-focus-portrait'),start:r('#conversation-start'),mute:r('#conversation-mute'),end:r('#conversation-end'),state:r('.state-console'),stage:r('.command-stage'),label:r('.crew-detail dt'),startup:r('.startup-stages li')};});
      assert(!metrics.overflow,`${name} ${width} overflow`);assert.equal(metrics.mic,0);
      if(name==='focus'){
        assert.equal(await page.locator('.halo-wrap').evaluate(e=>getComputedStyle(e).translate),'0px -20px','Maeve focused head halo lift');
        const controls=await page.locator('.primary-voice-actions button').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return{font:parseFloat(s.fontSize),height:r.height,top:r.top,bottom:r.bottom,left:r.left,right:r.right};}));
        assert.equal(controls.length,4);
        for(const c of controls){assert(c.font>=16&&c.height>=64,'Focused control readability');assert(c.top>=0&&c.bottom<=height-80&&c.left>=0&&c.right<=width,'Focused control clearance');assert(metrics.wave.bottom<=c.top,'Wave/control separation');}
      }
      if(name==='home'){assert(parseFloat(metrics.startup.font)>=16);assert(await page.evaluate(()=>{const card=document.querySelector('.startup-card'),last=document.querySelector('.startup-failure');return last.getBoundingClientRect().bottom<=card.getBoundingClientRect().bottom;}),'Startup content clipped');}
      if(name==='crew')assert(parseFloat(metrics.label.font)>=16);
      if(name==='focus'){const overlaps=(a,b)=>a.x<b.right&&a.right>b.x&&a.y<b.bottom&&a.bottom>b.y;assert(!overlaps(metrics.wave,metrics.state),`wave/state overlap ${width}`);for(const key of ['start','mute','end']){assert(!overlaps(metrics.wave,metrics[key]),`wave/${key} overlap ${width}`);assert(metrics[key].bottom<=height,`${key} clipped ${width}`);assert(metrics[key].x>=0&&metrics[key].right<=width);}assert(metrics.wave.y>metrics.portrait.y+metrics.portrait.height*.7,`wave enters upper portrait ${width}`);}
      if(name==='crew')await page.locator('#crew-detail').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(out,`${name}-${width}x${height}.png`)});results.push({name,width,height,metrics});
      if(name==='home'){await page.locator('#conversation-end').scrollIntoViewIfNeeded();assert(await page.locator('#conversation-end').evaluate(e=>{const r=e.getBoundingClientRect();return r.y>=76&&r.bottom<=innerHeight-38;}),'Home End not reachable above footer');await page.screenshot({path:path.join(out,`home-scrolled-${width}x${height}.png`)});}
    }
  }
  // Prove all three approved phone-size compositions render identically to
  // this same isolated baseline without the new desktop-only additions.
  for(const [width,height] of [[430,932],[393,852],[932,430]]){
    await page.setViewportSize({width,height});for(const url of ['/','/?focus=conversation','/?view=crew']){
      await ready(url);const after=await page.screenshot();
      await page.evaluate(()=>{document.querySelector('.voice-display').remove();document.querySelector('link[href*="desktop-readability"]').remove();});
      const before=await page.screenshot();assert(after.equals(before),`Mobile changed ${width} ${url}`);
      results.push({mobileIdentical:true,width,height,url});
    }
  }
  await page.setViewportSize({width:1920,height:1080});await ready('/?focus=conversation');
  await page.emulateMedia({reducedMotion:'no-preference'});
  const waveChecks=await page.evaluate(async()=>{let checks=0;for(const state of ['OFF','READY','LISTENING','SPEAKING','MUTED','THINKING','ENDED']){document.body.dataset.voiceState=state;await Promise.resolve();for(let n=0;n<20;n++)MAEVE_VOICE_DISPLAY.apply({low:1,mid:1,high:1},"playback");const ys=[...document.querySelectorAll('.voice-display path')].flatMap(p=>[...p.getAttribute('d').matchAll(/[ML] [\d.]+ ([\d.]+)/g)].map(m=>Number(m[1])));if(ys.some(y=>y<28||y>112))throw Error('Wave escaped bounds');if(state!=='SPEAKING'&&ys.some(y=>y!==70))throw Error('Fake inactive audio');checks++;}document.body.dataset.voiceState='OFF';MAEVE_VOICE_DISPLAY.apply({});return checks;});
  await page.evaluate(async()=>{document.body.dataset.voiceState='SPEAKING';await Promise.resolve();for(let i=0;i<20;i++)MAEVE_VOICE_DISPLAY.apply({low:1,mid:.8,high:.6},"playback");const label=document.createElement('div');label.textContent='SYNTHETIC MAXIMUM-WAVE PREVIEW — NO MICROPHONE OR PLAYBACK';label.style.cssText='position:fixed;top:78px;left:12px;z-index:100;background:#111;color:#ff9c55;padding:8px;font:14px sans-serif';document.body.append(label);});
  await page.screenshot({path:path.join(out,'focus-synthetic-wave-1920x1080.png')});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.evaluate(()=>{MAEVE_VOICE_DISPLAY.apply({low:1,mid:1,high:1},"playback");return [...document.querySelectorAll('.voice-display path')].every(p=>[...p.getAttribute('d').matchAll(/[ML] [\d.]+ ([\d.]+)/g)].every(m=>Number(m[1])===70));}),'Reduced motion not flat');
  assert.equal(external,0);results.push({waveChecks,reducedMotionFlat:true,externalRequests:external,microphoneCalls:0});
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(results,null,2));console.log(`PASS desktop views=9 mobile-identical=9 waveform-states=${waveChecks} external=0 microphone=0`);
}finally{if(browser)await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1});
