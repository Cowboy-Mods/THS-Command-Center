"use strict";
(() => {
  const MAX_MS=15000;
  const MAX_APPROVED_CHARS=800;
  const MIME_TYPES=["audio/webm;codecs=opus","audio/webm","audio/ogg;codecs=opus"];

  function create(config){
    const APPROVED_LABEL=config.approvedSelector,APPROVED_HEADER=config.approvedLabel;
    if(typeof APPROVED_LABEL!=="string"||typeof APPROVED_HEADER!=="string"||!APPROVED_LABEL||!APPROVED_HEADER)throw new Error("Approved microphone configuration is unavailable");
    const arm=document.getElementById("ptt-arm"),ptt=document.getElementById("ptt-hold"),endpoint=document.getElementById("ptt-endpoint"),microphone=document.getElementById("ptt-microphone"),originalTranscript=document.getElementById("ptt-original-transcript"),transcript=document.getElementById("ptt-transcript"),approvalActions=document.getElementById("ptt-approval-actions"),approve=document.getElementById("ptt-approve"),discard=document.getElementById("ptt-discard");
    const physicalMode=new URLSearchParams(location.search).get("ptt")==="physical-test";
    let approvedDeviceId=null,exactEndpointVerified=false,armed=false,releaseInterlockComplete=false,armPointerId=null;
    let attemptConsumed=false,holdActive=false,stream=null,recorder=null,chunks=[],startedPerf=0,stopPromise=null,maxTimer=null;
    let pendingTranscript=null,pendingTranscriptId=null,decisionConsumed=false;

    function state(name,detail){config.setState(name,detail);}
    function closeTracks(){const tracks=stream?stream.getTracks():[];for(const track of tracks)track.stop();const ended=tracks.every(track=>track.readyState==="ended");stream=null;return {count:tracks.length,ended};}
    function disable(){arm.disabled=true;ptt.disabled=true;}
    function hideDecision(){approvalActions.hidden=true;approve.disabled=true;discard.disabled=true;transcript.disabled=true;}
    function clearReview(){pendingTranscript=null;pendingTranscriptId=null;originalTranscript.textContent="No transcription.";transcript.value="";hideDecision();}
    function updateSendState(){const value=transcript.value.trim();approve.disabled=decisionConsumed||!pendingTranscriptId||!value||value.length>MAX_APPROVED_CHARS;}
    function fail(message){holdActive=false;clearTimeout(maxTimer);const closure=closeTracks();chunks=[];recorder=null;disable();clearReview();config.setBusy(false);microphone.textContent=`CLOSED — failure cleanup; all ended=${closure.ended}`;originalTranscript.textContent=message;state("FAILED","PTT STOPPED · NO RETRY");}
    function trustedMouse(event,target){return event.isTrusted&&event.target===target&&event.currentTarget===target&&event.isPrimary===true&&event.pointerType==="mouse"&&event.button===0&&!event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey;}
    function rejected(label){return label.startsWith("Default - ")||label.startsWith("Communications - ")||label.includes("(BT)")||label.includes("Hands-Free");}

    async function enumerateOnce(){
      if(!config.authorized||!navigator.mediaDevices?.enumerateDevices||!navigator.mediaDevices?.getUserMedia){state("UNAVAILABLE","PTT AUTHORIZATION OR MEDIA API UNAVAILABLE");disable();return;}
      const devices=await navigator.mediaDevices.enumerateDevices();
      const matches=devices.filter(device=>device.kind==="audioinput"&&device.label===APPROVED_LABEL&&!rejected(device.label)&&device.deviceId&&device.deviceId!=="default"&&device.deviceId!=="communications");
      if(matches.length!==1)throw new Error(`Approved microphone endpoint match count was ${matches.length}`);
      approvedDeviceId=matches[0].deviceId;exactEndpointVerified=true;
      config.onEndpointVerified?.(approvedDeviceId,APPROVED_LABEL);
      endpoint.textContent=`${APPROVED_LABEL} — exact physical endpoint verified; aliases and Bluetooth rejected`;
      if(!physicalMode){state("VERIFICATION_ONLY","EXACT ENDPOINT VERIFIED · MICROPHONE DISABLED");disable();return;}
      state("UNARMED","EXACT ENDPOINT VERIFIED · DELIBERATE ARM REQUIRED");arm.hidden=false;arm.disabled=false;ptt.disabled=true;
    }

    async function finish(reason){
      if(!stream||!recorder)return;
      clearTimeout(maxTimer);holdActive=false;
      const releasePerf=performance.now();
      if(recorder.state!=="inactive")recorder.stop();
      const closure=closeTracks();
      const closureLatencyMs=performance.now()-releasePerf;
      microphone.textContent=`CLOSED — ${closure.count} track(s), all ended=${closure.ended}, closure ${closureLatencyMs.toFixed(3)} ms`;
      ptt.classList.remove("is-listening");ptt.disabled=true;ptt.textContent="MIC CLOSED — TRANSCRIBING LOCALLY";
      state("TRANSCRIBING","LOCAL FASTER-WHISPER · TRANSCRIPT ONLY");
      if(!closure.ended)throw new Error("Microphone track closure could not be proven");
      await stopPromise;
      const durationMs=releasePerf-startedPerf;
      if(durationMs>MAX_MS+250)throw new Error("Recording exceeded the 15-second boundary");
      const blob=new Blob(chunks,{type:recorder.mimeType});
      chunks=[];recorder=null;
      const response=await config.apiFetch("/api/stt/transcribe",{method:"POST",headers:{"Content-Type":blob.type,"X-Endpoint-Label":APPROVED_HEADER,"X-Exact-Device-Match":"true","X-All-Tracks-Ended":"true","X-Recording-Duration-Ms":durationMs.toFixed(3),"X-Closure-Latency-Ms":closureLatencyMs.toFixed(3),"X-Stop-Reason":reason},body:blob});
      const data=await response.json();
      if(!response.ok||data.status!=="PASS"||typeof data.text!=="string")throw new Error(data.error||"Local transcription failed");
      if(!/^[a-f0-9]{32}$/.test(data.transcriptId||""))throw new Error("Local transcript identifier missing");
      pendingTranscript=data.text.trim();pendingTranscriptId=data.transcriptId;originalTranscript.textContent=pendingTranscript;transcript.value=pendingTranscript;transcript.disabled=false;
      microphone.textContent+=" — raw audio reference released";
      ptt.textContent="TRANSCRIPT LOCKED — PHYSICAL ATTEMPT CONSUMED";
      approvalActions.hidden=false;discard.disabled=false;updateSendState();
      state("AWAITING_APPROVAL","LOCAL TRANSCRIPT READY · NOTHING SENT · QWEN STOPPED");
    }

    async function begin(event){
      if(!physicalMode||!exactEndpointVerified||!armed||!releaseInterlockComplete||attemptConsumed||config.playbackActive()||!trustedMouse(event,ptt)||event.buttons!==1)return;
      attemptConsumed=true;holdActive=true;config.setBusy(true);ptt.setPointerCapture?.(event.pointerId);state("LISTENING","OPENING EXACT ROG 2.4 GHZ ENDPOINT");
      try{
        const requestedId=approvedDeviceId;
        const opened=await navigator.mediaDevices.getUserMedia({audio:{deviceId:{exact:requestedId}},video:false});
        stream=opened;
        const tracks=stream.getAudioTracks();
        const exact=tracks.length===1&&tracks[0].label===APPROVED_LABEL&&tracks[0].getSettings().deviceId===requestedId;
        if(!holdActive||!exact){const closed=closeTracks();microphone.textContent=`CLOSED — startup cancelled or endpoint rejected; all ended=${closed.ended}`;throw new Error(!holdActive?"Hold released before microphone startup completed":"Opened endpoint was not the approved microphone");}
        const mime=MIME_TYPES.find(type=>MediaRecorder.isTypeSupported(type));
        if(!mime){closeTracks();throw new Error("No approved in-memory recorder format is available");}
        chunks=[];recorder=new MediaRecorder(stream,{mimeType:mime,audioBitsPerSecond:128000});
        stopPromise=new Promise((resolve,reject)=>{recorder.ondataavailable=event=>{if(event.data?.size)chunks.push(event.data);};recorder.onstop=resolve;recorder.onerror=event=>reject(event.error||new Error("MediaRecorder error"));});
        recorder.start();startedPerf=performance.now();ptt.disabled=false;ptt.classList.add("is-listening");ptt.textContent="LISTENING — RELEASE TO STOP";microphone.textContent=`${APPROVED_LABEL} — one live track`;state("LISTENING","RECORDING ONLY WHILE PHYSICALLY HELD");
        maxTimer=setTimeout(()=>{holdActive=false;finish("15-second-limit").catch(error=>fail(error.message));},MAX_MS);
      }catch(error){fail(error instanceof Error?error.message:"PTT startup failed");}
    }
    function release(reason){if(!holdActive)return;holdActive=false;if(stream&&recorder)finish(reason).catch(error=>fail(error.message));}
    function armDown(event){if(!physicalMode||!exactEndpointVerified||armed||attemptConsumed||config.playbackActive()||!trustedMouse(event,arm)||event.buttons!==1)return;armed=true;releaseInterlockComplete=false;armPointerId=event.pointerId;arm.setPointerCapture?.(event.pointerId);state("ARMED","RELEASE POINTER · THEN HOLD PUSH-TO-TALK");}
    function armUp(event){if(!armed||releaseInterlockComplete||event.pointerId!==armPointerId||!trustedMouse(event,arm)||event.buttons!==0)return;releaseInterlockComplete=true;armPointerId=null;arm.disabled=true;ptt.disabled=false;state("ARMED","FRESH RELEASE PROVED · HOLD PUSH-TO-TALK WHEN READY");}
    async function sendDecision(event){if(!event.isTrusted||decisionConsumed||!pendingTranscript||!pendingTranscriptId)return;const approvedText=transcript.value.trim();transcript.value=approvedText;if(!approvedText||approvedText.length>MAX_APPROVED_CHARS){updateSendState();return;}decisionConsumed=true;hideDecision();state("THINKING","EDITED APPROVAL CONSUMED · RESTRICTED OPENAI TEXT REASONING");try{const result=await config.approveAndRespond(pendingTranscriptId,approvedText);clearReview();ptt.textContent=result?.cancelled?"RESPONSE CANCELLED — NEW AUTHORIZATION REQUIRED":"COMPLETED — NEW AUTHORIZATION REQUIRED";config.setBusy(false);state("READY",result?.cancelled?"RESPONSE CANCELLED · MICROPHONE CLOSED":"OPENAI RESPONSE SPOKEN LOCALLY · APPROVAL CONSUMED");}catch(error){config.setBusy(false);ptt.textContent="RESPONSE FAILED — APPROVED TRANSCRIPT RETAINED IN MEMORY";state("FAILED",error instanceof Error?error.message:"CONTROLLED RESPONSE FAILED");}}
    async function discardDecision(event){if(!event.isTrusted||decisionConsumed||!pendingTranscriptId)return;decisionConsumed=true;hideDecision();try{await config.discardTranscript(pendingTranscriptId);clearReview();ptt.textContent="DISCARDED — NEW AUTHORIZATION REQUIRED";config.setBusy(false);state("IDLE","PENDING TRANSCRIPT DISCARDED · QWEN NOT STARTED");}catch(error){clearReview();config.setBusy(false);state("FAILED",error instanceof Error?error.message:"TRANSCRIPT DISCARD FAILED");}}

    if(physicalMode){
      arm.addEventListener("pointerdown",armDown);arm.addEventListener("pointerup",armUp);arm.addEventListener("pointercancel",()=>{armPointerId=null;});
      for(const eventName of ["click","keydown","contextmenu"])arm.addEventListener(eventName,event=>event.preventDefault());
      ptt.addEventListener("pointerdown",begin);ptt.addEventListener("pointerup",()=>release("pointerup"));ptt.addEventListener("pointercancel",()=>release("pointercancel"));ptt.addEventListener("lostpointercapture",()=>release("lostpointercapture"));
      for(const eventName of ["click","keydown","contextmenu"])ptt.addEventListener(eventName,event=>event.preventDefault());
      transcript.addEventListener("input",updateSendState);
      approve.addEventListener("click",sendDecision);
      discard.addEventListener("click",discardDecision);
      for(const control of [approve,discard])control.addEventListener("contextmenu",event=>event.preventDefault());
      window.addEventListener("blur",()=>release("blur"));window.addEventListener("pagehide",()=>release("pagehide"));document.addEventListener("visibilitychange",()=>{if(document.hidden)release("visibilitychange");});
    }
    navigator.mediaDevices?.addEventListener?.("devicechange",()=>{if(!attemptConsumed)fail("Audio device inventory changed; reload is not permitted")});
    state(config.authorized?"UNAVAILABLE":"UNAVAILABLE",config.authorized?"VERIFYING EXACT AUDIO ENDPOINT":"VALID LAUNCH TOKEN REQUIRED");
    if(config.authorized)enumerateOnce().catch(error=>fail(error instanceof Error?error.message:"Endpoint verification failed"));
    return Object.freeze({ensureMicrophoneClosed(){holdActive=false;clearTimeout(maxTimer);const closure=closeTracks();microphone.textContent=`CLOSED — cancellation cleanup; all ended=${closure.ended}`;return closure;},shutdown(){holdActive=false;clearTimeout(maxTimer);closeTracks();clearReview();decisionConsumed=true;disable();config.setBusy(false);}});
  }
  globalThis.MAEVE_PTT_CONTROLLER=Object.freeze({create});
})();
