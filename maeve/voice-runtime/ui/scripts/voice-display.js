"use strict";
(function (global) {
  // No microphone, AudioContext, clock, or provider is created here.
  // Only the validated playback analyser supplies live amplitudes.
  const ids = ["voice-line-low", "voice-line-mid", "voice-line-high"];
  let smoothed = [0, 0, 0];
  function apply(values = {}, source = "none") {
    const active = source === "playback" && document.body.dataset.voiceState === "SPEAKING";
    const frozen = global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const bands = [values.low, values.mid, values.high];
    ids.forEach((id, band) => {
      const path = document.getElementById(id);
      if (!path) return;
      const sample = Math.max(0, Math.min(1, Number(bands[band]) || 0));
      smoothed[band] = !active || frozen || sample === 0 ? 0 : smoothed[band] * .55 + sample * .45;
      const amplitude = smoothed[band] * 42;
      // Fixed 28..372 x and 28..112 y envelope cannot escape the display.
      const points = [];
      for (let i = 0; i <= 160; i++) {
        const t = i / 160;
        const y = 70 + Math.sin(t * Math.PI * (6 + band * 2) + band * 1.2) * Math.sin(t * Math.PI) ** 2 * amplitude;
        points.push(`${i ? "L" : "M"} ${(28 + 344 * t).toFixed(2)} ${y.toFixed(2)}`);
      }
      path.setAttribute("d", points.join(" "));
    });
  }
  global.MAEVE_VOICE_DISPLAY = Object.freeze({apply});
  new MutationObserver(() => apply({})).observe(document.body, {attributes:true, attributeFilter:["data-voice-state"]});
  apply({});
})(globalThis);
