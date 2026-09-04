const {chromium}=require('playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const origin='http://127.0.0.1:48179';
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const results=[];
 for(const reducedMotion of ['no-preference','reduce'])for(const delay of [0,200]){
 const context=await browser.newContext({viewport:{width:2560,height:1440},reducedMotion});let requests=0;
 await context.addInitScript(delay=>{window.forbidden=0;const deny=()=>{window.forbidden++;throw Error('No audio allowed');};navigator.mediaDevices.getUserMedia=deny;window.AudioContext=deny;window.webkitAudioContext=deny;HTMLMediaElement.prototype.play=deny;navigator.mediaDevices.enumerateDevices=async()=>{await new Promise(r=>setTimeout(r,delay));return[{kind:'audioinput',label:'Synthetic microphone exact endpoint',deviceId:'synthetic-endpoint'}];};},delay);
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==origin){requests++;return r.abort();}if(u.pathname==='/health')return r.fulfill({json:{runtime:'maeve-v2-live',version:'0.5.0-stage13',microphone:'PTT_ONLY_CLOSED',networkProvider:'OPENAI_CODEX_ONLY',localModelNetwork:'BLOCKED',gpuOwner:'NONE',reasoningProvider:'OPENAI_CODEX_SUBSCRIPTION',reasoningModel:'gpt-5.6-sol',reasoningToolEvents:0,sttState:'READY',voiceState:'IDLE',runMode:'CONTROLLED_CONVERSATION',voiceProvider:{provider:'ELEVENLABS',display:'SYNTHETIC',available:true}}});if(u.pathname==='/api/config')return r.fulfill({json:{microphone:{approvedLabel:'Synthetic microphone',approvedSelector:'Synthetic microphone exact endpoint'}}});if(u.pathname.startsWith('/api/')){requests++;return r.abort();}return r.continue();});
 const page=await context.newPage();await page.goto(origin+'/?ptt=physical-test#token='+'a'.repeat(64));await page.waitForTimeout(500);
 for(const focus of [false,true]){if(focus)await page.evaluate(()=>MAEVE_INTEGRATED_UI.openConversationMode());const data=await page.evaluate(()=>{const e=document.querySelector('#halo-breath'),s=getComputedStyle(e),w=getComputedStyle(e.parentElement.parentElement);return{state:document.body.dataset.voiceState,session:document.querySelector('#conversation-session').dataset.state,animation:s.animationName,duration:s.animationDuration,iterations:s.animationIterationCount,easing:s.animationTimingFunction,opacity:s.opacity,stroke:s.strokeWidth,filter:s.filter,origin:s.transformOrigin,wrapOpacity:w.opacity,z:w.zIndex,label:document.querySelector('#halo-state').textContent,reduced:matchMedia('(prefers-reduced-motion:reduce)').matches,forbidden:window.forbidden};});results.push({delay,reducedMotion,focus,...data});}
 for(const item of results.filter(x=>x.delay===delay&&x.reducedMotion===reducedMotion)){
 assert.equal(item.animation,reducedMotion==='reduce'?'none':'halo-idle-visible');
 assert.equal(item.forbidden,0);assert.equal(item.label.includes('REDUCED MOTION'),reducedMotion==='reduce');
 if(reducedMotion==='no-preference'){assert.equal(item.duration,'3.6s');assert.equal(item.iterations,'infinite');}
 }
 for(const state of ['OFF','ENDED','MUTED','LISTENING','PROCESSING','SPEAKING']){
 await page.evaluate(state=>document.body.dataset.voiceState=state,state);
 await page.waitForTimeout(30);assert.equal(await page.locator('#halo-breath').evaluate(e=>getComputedStyle(e).animationName),'none',state);
 }
 await page.evaluate(()=>{document.querySelector('[data-stage="maeve-ready"]').classList.remove('is-passed');document.body.dataset.voiceState='READY';});
 await page.waitForTimeout(30);assert.equal(await page.locator('#halo-breath').evaluate(e=>getComputedStyle(e).animationName),'none');
 assert.equal(requests,0);await context.close();}
 const context=await browser.newContext({reducedMotion:'no-preference'});let forbidden=0;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==origin||u.pathname.startsWith('/api/')||u.pathname==='/health'){forbidden++;return r.abort();}return r.continue();});
 const page=await context.newPage();
 for(const [width,height] of [[2560,1440],[1920,1080],[1280,720],[430,932],[393,852],[932,430]]){
 await page.setViewportSize({width,height});await page.goto(origin+'/?synthetic=success&focus=conversation');await page.waitForTimeout(300);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.equal(await page.locator('.primary-voice-actions button:disabled').count(),4);
 assert.equal(await page.locator('#halo-breath').evaluate(e=>getComputedStyle(e).animationName),'halo-idle-visible');
 }
 await page.setViewportSize({width:2560,height:1440});
 const samples=[];for(let i=0;i<17;i++){samples.push(Number(await page.locator('#halo-breath').evaluate(e=>getComputedStyle(e).opacity)));await page.waitForTimeout(450);}
 assert(Math.max(...samples)-Math.min(...samples)>.55,'Visible two-cycle opacity range');
 const out=path.resolve(__dirname,'../evidence/idle-halo-20260903');fs.mkdirSync(out,{recursive:true});
 await page.screenshot({path:path.join(out,'focused-normal.png')});
 await page.goto(origin+'/?synthetic=success');await page.waitForTimeout(1800);await page.screenshot({path:path.join(out,'home-normal.png')});
 assert.equal(forbidden,0);await context.close();
 fs.writeFileSync(path.join(out,'computed.json'),JSON.stringify({results,samples,forbidden},null,2));
 console.log(JSON.stringify(results,null,2));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
