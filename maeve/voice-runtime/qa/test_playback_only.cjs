const {chromium}=require('playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const origin='http://127.0.0.1:48179';
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});try{
 const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'no-preference'});let forbidden=0;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==origin||u.pathname.startsWith('/api/')||u.pathname==='/health'){forbidden++;return r.abort();}return r.continue();});
 await context.addInitScript(()=>{window.forbidden=0;const deny=()=>{window.forbidden++;throw Error('No live audio allowed');};navigator.mediaDevices.getUserMedia=deny;window.AudioContext=deny;window.webkitAudioContext=deny;HTMLMediaElement.prototype.play=deny;});
 const page=await context.newPage();await page.goto(origin+'/?synthetic=success&focus=conversation');await page.waitForTimeout(300);
 const result=await page.evaluate(async()=>{
 const flat=()=>[...document.querySelectorAll('.voice-display path')].every(p=>[...p.getAttribute('d').matchAll(/[ML] [\d.]+ ([\d.]+)/g)].every(m=>Number(m[1])===70));
 let checks=0;
 for(const state of ['READY','LISTENING','PROCESSING_STT','THINKING','PROCESSING','SPEAKING','MUTED','ENDED','OFF'])for(const source of ['microphone','none','playback']){
 document.body.dataset.voiceState=state;await new Promise(r=>requestAnimationFrame(r));
 for(let i=0;i<20;i++)MAEVE_HALO_ANALYZER.applyValues({low:1,mid:.8,high:.6},source);
 const expected=state==='SPEAKING'&&source==='playback';if(flat()===expected)throw Error(state+' '+source+' incorrect wave gate');checks++;
 }
 // Exercise the actual analyser bridge with synthetic bins, not audio devices.
 document.body.dataset.voiceState='SPEAKING';await Promise.resolve();
 const fake={frequencyBinCount:512,connect(){},getByteFrequencyData(b){b.fill(200);}};
 const bridge=MAEVE_HALO_ANALYZER.create({createAnalyser:()=>fake},{connect(){}});bridge.start();if(flat())throw Error('Playback bridge disconnected');bridge.stop();if(!flat())throw Error('Stop did not flatten');
 document.body.dataset.voiceState='READY';await new Promise(r=>requestAnimationFrame(r));
 if(getComputedStyle(document.querySelector('#halo-breath')).animationName!=='halo-idle-visible'||!flat())throw Error('Idle systems coupled');
 for(const state of ['PROCESSING_STT','THINKING']){setState(state,'STATIC PROCESSING CHECK');await new Promise(r=>requestAnimationFrame(r));if(document.querySelector('#runtime-state').textContent!=='PROCESSING')throw Error('Missing processing status');if(!flat())throw Error('Processing wave');}
 return {sourceStateChecks:checks,playbackBridge:true,idleIndependent:true,processingStatus:true,forbidden:window.forbidden};});
 assert.equal(result.forbidden,0);assert.equal(forbidden,0);
 const runtime=fs.readFileSync(path.join(__dirname,'../ui/scripts/runtime.js'),'utf8');const controller=fs.readFileSync(path.join(__dirname,'../ui/scripts/conversation-controller.js'),'utf8');assert(!runtime.includes('onMicAmplitude'));assert(!controller.includes('onMicAmplitude'));
 console.log(JSON.stringify(result));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
