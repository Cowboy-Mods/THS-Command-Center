"use strict";
// Visual state only. No capture, timers, provider, or conversation transitions.
document.addEventListener("DOMContentLoaded", () => {
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const label = document.getElementById("halo-state");
  const ready = document.querySelector('[data-stage="maeve-ready"]');
  const preview = location.port === "48179" && new URLSearchParams(location.search).get("synthetic") === "success";
  function update() {
    const state = document.body.dataset.voiceState;
    // Endpoint discovery may finish after readiness. UNARMED is still idle,
    // but only after every authenticated startup stage has passed.
    const idle = (state === "READY" || state === "UNARMED") && ready.classList.contains("is-passed");
    document.body.dataset.haloIdle = String(idle);
    const suffix = " · BREATHING DISABLED — REDUCED MOTION";
    let text = label.textContent.replace(suffix, "");
    if (idle) text = preview ? "STATIC IDLE PREVIEW — NO VOICE SERVICES" : "READY — MICROPHONE CLOSED";
    if (idle && motion.matches) text += suffix;
    label.textContent = text;
    if (preview) document.querySelectorAll('.primary-voice-actions button').forEach(button => { button.disabled = true; });
  }
  new MutationObserver(update).observe(document.body, {attributes:true, attributeFilter:["data-voice-state"]});
  new MutationObserver(update).observe(ready, {attributes:true, attributeFilter:["class"]});
  motion.addEventListener("change", update);
  update();
});
