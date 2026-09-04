/* Replays existing assertions unchanged; only isolates server, evidence and browser permissions. */
const fs=require('fs'),path=require('path'),os=require('os'),http=require('http'),Module=require('module');
const root=process.env.MAEVE_QA_ROOT,ui=path.join(root,'ui'),test=process.argv[2];
if(!/^test_(close_control|desktop_correction|specialist_focus|halo_layer|idle_halo|playback_only)\.cjs$/.test(test))throw Error('Unexpected test');
const evidence=path.join(process.env.MAEVE_QA_TEMP,'browser-evidence',test.replace('.cjs',''));
fs.mkdirSync(evidence,{recursive:true});
const profile=fs.mkdtempSync(path.join(process.env.MAEVE_QA_TEMP,'maeve-offline-edge-'));
const pw=require('playwright');
const originalLaunch=pw.chromium.launch.bind(pw.chromium);let server,browser,violations=[];
const origin='http://127.0.0.1:48179';
pw.chromium.launch=async options=>{
 browser=await originalLaunch({...options,headless:true,downloadsPath:profile,env:{...process.env,TMP:profile,TEMP:profile},args:[...(options.args||[]),'--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check','--disable-domain-reliability','--disable-features=MediaRouter,OptimizationHints','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--autoplay-policy=user-gesture-required','--proxy-server=http://127.0.0.1:9','--proxy-bypass-list=127.0.0.1']});
 const originalContext=browser.newContext.bind(browser);
 browser.newContext=async options=>{
  const context=await originalContext({...options,permissions:[],acceptDownloads:false,serviceWorkers:'block'});
  const route=context.route.bind(context);
  context.route=async(pattern,handler,opts)=>route(pattern,async(r,...rest)=>{
   const u=new URL(r.request().url());if(u.origin!==origin){violations.push('non-loopback');return r.abort();}
   // API requests can only be fulfilled synthetically by an existing test;
   // they can never reach an operational service through continue/fallback.
   if(u.pathname==='/health'||u.pathname.startsWith('/api/')){
    r.continue=async()=>{violations.push('operational-endpoint');return r.abort();};
    r.fallback=r.continue;
   }
   return handler(r,...rest);
  },opts);
  await context.route('**/*',r=>r.continue());
  await context.addInitScript(()=>{
   const deny=()=>Promise.reject(new Error('Device unavailable in offline rehearsal'));
   for(const key of ['getUserMedia','getDisplayMedia'])if(navigator.mediaDevices)navigator.mediaDevices[key]=deny;
   if(navigator.mediaDevices)navigator.mediaDevices.enumerateDevices=async()=>[];
   navigator.requestMIDIAccess=deny;
   if(navigator.clipboard)for(const k of ['read','write','readText','writeText'])navigator.clipboard[k]=deny;
   if(navigator.geolocation)for(const k of ['getCurrentPosition','watchPosition'])navigator.geolocation[k]=()=>{throw Error('Geolocation denied');};
   for(const name of ['usb','serial','bluetooth','hid'])if(navigator[name])for(const key of ['requestDevice','requestPort','getDevices','getPorts'])if(key in navigator[name])navigator[name][key]=deny;
   if(window.Notification)Notification.requestPermission=async()=>'denied';
   HTMLMediaElement.prototype.play=deny;window.AudioContext=window.webkitAudioContext=function(){throw Error('Audio denied');};
  });
  return context;
 };
 return browser;
};
(async()=>{
 server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(new URL(req.url,origin).pathname),file=path.resolve(ui,'.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(ui+path.sep)||pathname==='/health'||pathname.startsWith('/api/')){res.writeHead(403);return res.end();}
  try{res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.webmanifest':'application/manifest+json'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(48179,'127.0.0.1',resolve);});
 let code=fs.readFileSync(path.join(root,'qa',test),'utf8');
 // Existing tests that own ephemeral servers are redirected to this one owned server.
 code=code.replace("await new Promise(r=>server.listen(0,'127.0.0.1',r))",'Promise.resolve()').replaceAll('server.address().port','48179');
 code=code.replaceAll(/path\.resolve\(__dirname,'\.\.\/evidence\/([^']+)'\)/g,(_,name)=>JSON.stringify(path.join(evidence,name)));
 const m=new Module(path.join(root,'qa',test),module);m.filename=path.join(root,'qa',test);m.paths=Module._nodeModulePaths(path.join(root,'qa'));m._compile(code,m.filename);
 // Test IIFEs own browser.close; wait for disconnect without a polling retry.
 const timer=setInterval(()=>{if(browser&&!browser.isConnected()){clearInterval(timer);server.close();if(violations.length){console.error(violations);process.exitCode=1;}fs.writeFileSync(path.join(evidence,'isolation.json'),JSON.stringify({profilePolicy:'preserved outside repository; browser-owned child profile cleaned by Playwright',violations,headless:true,origin},null,2));}},100);
 process.on('uncaughtException',async error=>{console.error(error);process.exitCode=1;clearInterval(timer);if(browser)await browser.close();server.close();});
})().catch(async e=>{console.error(e);process.exitCode=1;if(browser)await browser.close();if(server)server.close();});
