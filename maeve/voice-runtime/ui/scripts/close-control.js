"use strict";
(() => {
  function create(config) {
    const panel=document.querySelector('[data-view-panel="control"]');
    const card=document.createElement('section');card.className='command-card runtime-close-card';
    card.innerHTML='<div><p class="eyebrow">Local runtime</p><h2>Close Maeve safely</h2><p>End the conversation and shut down Maeve’s local voice services.</p></div><button type="button" id="control-close-maeve">CLOSE MAEVE</button>';
    panel.querySelector('.view-header').after(card);
    const dialog=document.createElement('dialog');dialog.id='close-maeve-dialog';dialog.setAttribute('aria-labelledby','close-maeve-title');dialog.setAttribute('aria-describedby','close-maeve-explanation');
    dialog.innerHTML='<h2 id="close-maeve-title">CLOSE MAEVE?</h2><p id="close-maeve-explanation">This will end the conversation, close the microphone, clear its context, and shut down voice services and the local Maeve interface.</p><p id="close-maeve-status" role="status" aria-live="polite"></p><div class="close-maeve-actions"><button type="button" id="close-maeve-cancel">CANCEL</button><button type="button" id="close-maeve-confirm">END AND CLOSE</button></div>';
    document.body.append(dialog);
    const openButton=card.querySelector('button'),cancel=dialog.querySelector('#close-maeve-cancel'),confirm=dialog.querySelector('#close-maeve-confirm'),status=dialog.querySelector('#close-maeve-status');
    let attempted=false,returnFocus=null;
    function open(){if(attempted)return;returnFocus=document.activeElement;status.textContent=config.authorized?'':'CERTIFIED LAUNCH REQUIRED — shutdown is unavailable in this static preview.';confirm.disabled=!config.authorized;if(!dialog.open)dialog.showModal();cancel.focus();}
    function dismiss(){if(attempted)return;dialog.close();returnFocus?.focus();}
    cancel.addEventListener('click',dismiss);dialog.addEventListener('cancel',event=>{event.preventDefault();dismiss();});openButton.addEventListener('click',open);
    confirm.addEventListener('click',async()=>{
      if(attempted||!config.authorized)return;
      attempted=true;confirm.disabled=true;cancel.disabled=true;openButton.disabled=true;
      status.textContent='CLOSING MAEVE — ending conversation and closing microphone…';
      let timer;
      try{
        await Promise.race([config.prepare(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('CLEANUP_TIMEOUT')),30000);})]);clearTimeout(timer);
        config.setState('STOPPING','CLOSING MAEVE · MICROPHONE CLOSED · CONTEXT CLEARED');
        status.textContent='CLOSING MAEVE — authenticated shutdown requested…';
        const abort=new AbortController();timer=setTimeout(()=>abort.abort(),30000);
        const response=await config.apiFetch('/api/runtime/close',{method:'POST',signal:abort.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'close-maeve',runtimeVersion:config.runtimeVersion})});
        const data=await response.json();if(!response.ok||data.status!=='STOPPING'||data.microphone!=='CLOSED')throw Error('CLOSE_REJECTED');
        clearTimeout(timer);status.textContent='SHUTDOWN ACCEPTED — Maeve is closing. If this tab remains, close it after the launcher reports MAEVE_LAUNCHER_STOPPED.';
        config.closeWindow();
      }catch(_error){clearTimeout(timer);status.textContent='CLOSE MAEVE FAILED — no automatic retry. Keep this message visible. Use the Maeve launcher window and press Ctrl+C once for owned graceful shutdown.';config.setState('FAILED','CLOSE MAEVE FAILED · MANUAL RECOVERY REQUIRED');}
    });
    return Object.freeze({open});
  }
  globalThis.MAEVE_CLOSE_CONTROL=Object.freeze({create});
})();
