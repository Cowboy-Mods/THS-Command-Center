"use strict";
// Visual-only crew screen. No voice routing or fallback is implemented here.
document.addEventListener("DOMContentLoaded", () => {
  const ui = globalThis.MAEVE_INTEGRATED_UI;
  const detail = document.getElementById("crew-detail");
  const detailName = document.getElementById("crew-detail-name");
  const talk = document.createElement("button");
  talk.id = "specialist-talk";
  talk.type = "button";
  talk.hidden = true;
  detail.append(talk);
  const notice = document.createElement("p");
  notice.id = "specialist-open-notice";
  notice.setAttribute("role", "status");
  notice.hidden = true;
  detail.append(notice);
  const screen = document.createElement("dialog");
  screen.id = "specialist-focus";
  screen.setAttribute("aria-labelledby", "specialist-name");
  screen.setAttribute("aria-describedby", "specialist-connection");
  screen.innerHTML = `<div class="specialist-shell">
    <nav class="specialist-returns" aria-label="Return from specialist preview"><button type="button" id="specialist-return-crew">RETURN TO CREW</button><button type="button" id="specialist-return-maeve">RETURN TO MAEVE</button></nav>
    <header class="specialist-identity"><h1 id="specialist-name"></h1><p id="specialist-role"></p></header>
    <div class="specialist-stage"><div class="specialist-static-halo" aria-hidden="true"></div><img id="specialist-portrait" alt=""><div class="specialist-wave" aria-label="Inactive voice display — no specialist audio connection"></div></div>
    <section class="specialist-status" role="status"><strong id="specialist-connection">SPECIALIST VOICE — NOT YET CONNECTED</strong><p>ROUTING NOT YET CONNECTED · MICROPHONE CLOSED · NO AUDIO</p><p>Readiness: NOT VERIFIED. Visual preview only; no conversation can start.</p></section>
    <div class="specialist-voice-controls" aria-label="Unavailable specialist conversation controls"><button type="button" disabled>START CONVERSATION</button><button type="button" disabled>MUTE</button><button type="button" disabled>END CONVERSATION</button><button type="button" disabled>CANCEL CONVERSATION</button></div>
  </div>`;
  document.body.append(screen);
  // Reuse the approved vector display shape, but never subscribe this clone
  // to Maeve's analyser. Its lines stay flat and it has no active DOM IDs.
  const waveform = document.querySelector(".voice-display svg").cloneNode(true);
  waveform.removeAttribute("aria-labelledby");
  waveform.setAttribute("aria-label", "Inactive horizontal voice lines");
  waveform.querySelector("defs")?.remove();
  waveform.querySelectorAll("[id]").forEach(node => node.removeAttribute("id"));
  waveform.querySelectorAll("[clip-path]").forEach(node => node.removeAttribute("clip-path"));
  waveform.querySelectorAll("path").forEach(node => node.setAttribute("d", "M 28 70 L 372 70"));
  screen.querySelector(".specialist-wave").append(waveform);
  let selected = null;
  function syncTalk() {
    const member = ui.crew.find(item => item.name === detailName.textContent);
    talk.hidden = !member;
    talk.textContent = member ? `TALK TO ${member.name}` : "";
    talk.dataset.crewId = member?.id || "";
    notice.hidden = true;
  }
  function open(id) {
    const member = ui.crew.find(item => item.id === id);
    if (!member || screen.open) return false;
    const state = document.body.dataset.voiceState || "OFF";
    if (!["OFF", "ENDED", "FAILED"].includes(state)) {
      notice.textContent = "End the current Maeve session before opening a specialist preview.";
      notice.hidden = false;
      return false;
    }
    selected = member;
    screen.dataset.crewId = member.id;
    screen.querySelector("#specialist-name").textContent = member.name;
    screen.querySelector("#specialist-role").textContent = member.role;
    const portrait = screen.querySelector("#specialist-portrait");
    portrait.src = member.portrait;
    portrait.alt = `Approved portrait of ${member.name}, ${member.role}`;
    screen.showModal();
    screen.querySelector("#specialist-return-crew").focus();
    return true;
  }
  function returnToCrew() {
    screen.close();
    ui.openView("crew");
    if (selected) ui.openCrewDetail(selected.id);
    talk.focus();
  }
  function returnToMaeve() {
    screen.close();
    ui.openView("home");
    ui.closeConversationMode();
  }
  talk.addEventListener("click", () => open(talk.dataset.crewId));
  screen.querySelector("#specialist-return-crew").addEventListener("click", returnToCrew);
  screen.querySelector("#specialist-return-maeve").addEventListener("click", returnToMaeve);
  screen.addEventListener("cancel", event => { event.preventDefault(); returnToCrew(); });
  screen.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const first = screen.querySelector("#specialist-return-crew");
    const last = screen.querySelector("#specialist-return-maeve");
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  new MutationObserver(syncTalk).observe(detailName, {childList:true, subtree:true, characterData:true});
  syncTalk();
  const requested = new URLSearchParams(location.search).get("specialist");
  if (requested) open(requested);
});
