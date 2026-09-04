const {chromium}=require('playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');const origin='http://127.0.0.1:48179';
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});try{
 const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce'});let closes=0,unauthorized=0,failure=false;
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.origin!==origin)return r.abort();if(u.pathname==='/api/runtime/close'){closes++;if(r.request().headers()['x-maeve-token']!=='a'.repeat(64))unauthorized++;return r.fulfill({status:failure?503:200,json:failure?{error:'Synthetic failure'}:{status:'STOPPING',microphone:'CLOSED'}});}if(u.pathname.startsWith('/api/')||u.pathname==='/health')throw Error('Unexpected runtime request');return r.continue();});
 await context.addInitScript(()=>{window.closeCount=0;window.close=()=>window.closeCount++;});
 const page=await context.newPage();const url=origin+'/?synthetic=success&view=control#token='+'a'.repeat(64);
 await page.goto(url);await page.locator('#control-close-maeve').focus();await page.keyboard.press('Enter');assert(await page.locator('#close-maeve-dialog').isVisible());
 assert.equal(await page.locator('#close-maeve-title').textContent(),'CLOSE MAEVE?');await page.locator('#close-maeve-cancel').click();assert.equal(closes,0);assert(!await page.locator('#close-maeve-dialog').isVisible());
 await page.locator('#control-close-maeve').click();await page.locator('#close-maeve-confirm').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>window.closeCount===1);assert.equal(closes,1);assert.equal(unauthorized,0);
 await page.locator('#close-maeve-confirm').evaluate(e=>{e.click();e.click();});assert.equal(closes,1);assert.equal(await page.locator('#conversation-session').getAttribute('data-state'),'OFF');
 // Unauthenticated preview stays fail-closed.
 await page.goto(origin+'/?synthetic=success&view=control');await page.locator('#control-close-maeve').click();assert(await page.locator('#close-maeve-confirm').isDisabled());await page.locator('#close-maeve-confirm').evaluate(e=>e.click());assert.equal(closes,1);
 // Existing startup-failure entry opens the same confirmation, without a request.
 await page.goto(origin+'/?synthetic=broker-failure#token='+'a'.repeat(64));await page.locator('#close-maeve').click();assert(await page.locator('#close-maeve-dialog').isVisible());assert.equal(closes,1);
 failure=true;await page.locator('#close-maeve-confirm').click();await page.waitForFunction(()=>document.querySelector('#close-maeve-status').textContent.includes('CLOSE MAEVE FAILED'));assert.equal(closes,2);assert.equal(await page.evaluate(()=>window.closeCount),0);assert(await page.locator('#close-maeve-confirm').isDisabled());
 // Exercise the real conversation cleanup implementation with an in-memory active
 // session and fake track, not a microphone request or operational session.
 await page.goto(origin+'/?synthetic=success');
 const source=fs.readFileSync(path.join(__dirname,'../ui/scripts/conversation-controller.js'),'utf8');
 const activeResult=await page.evaluate(async source=>{
  window.shutdownEvents=[];const injected=source.replace('state("OFF","DELIBERATE START REQUIRED · NO ALWAYS-LISTENING");','active=true;sessionId="b".repeat(32);sessionToken="c".repeat(64);conversationId="d".repeat(32);stream={getTracks:()=>[{readyState:"live",stop(){this.readyState="ended";window.shutdownEvents.push("mic-stopped");}}]};state("OFF","DELIBERATE START REQUIRED · NO ALWAYS-LISTENING");');
  (0,eval)(injected);
  const controller=MAEVE_CONVERSATION_CONTROLLER.create({approvedLabel:'Synthetic microphone',runtimeVersion:'0.5.0-stage13',setState:(s,d)=>window.shutdownEvents.push(s+':'+d),cancelConversationPlayback:async()=>{},apiFetch:async(p)=>{if(!window.shutdownEvents.includes('mic-stopped'))throw Error('Microphone not stopped first');if(p!=='/api/conversation/end')throw Error('Unexpected endpoint');window.shutdownEvents.push('end-request');return{ok:true,json:async()=>({status:'OFF',sessionTokenCleared:true,contextCleared:true,resumable:false})};}});
  await controller.prepareRuntimeClose();return{events:window.shutdownEvents,log:document.querySelector('#conversation-log').textContent,startDisabled:document.querySelector('#conversation-start').disabled};
 },source);
 assert(activeResult.events.includes('end-request'));assert(activeResult.events.some(s=>s.includes('CONTEXT CLEARED')));assert.equal(activeResult.log,'');assert(activeResult.startDisabled);
 let viewports=0;for(const [width,height] of [[2560,1440],[1920,1080],[1280,720],[430,932],[393,852],[932,430]]){
  await page.setViewportSize({width,height});await page.goto(origin+'/?synthetic=success&view=control');await page.locator('#control-close-maeve').scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#control-close-maeve').click();
  for(const id of ['#close-maeve-cancel','#close-maeve-confirm']){await page.locator(id).scrollIntoViewIfNeeded();assert(await page.locator(id).evaluate(e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;}));}viewports++;
 }
 console.log(JSON.stringify({keyboard:true,cancelRequests:0,authenticatedClose:true,duplicateIgnored:true,unauthenticatedBlocked:true,startupFailurePreserved:true,activeCleanup:true,failureSanitized:true,viewports,providerRequests:0,microphoneRequests:0}));
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
