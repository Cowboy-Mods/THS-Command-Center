"use strict";

(function publishHaloAnalyzer(global) {
  const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));

  function reducedMotionActive() {
    return global.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function applyValues(values = {}) {
    const low = clamp(values.low);
    const mid = clamp(values.mid);
    const high = clamp(values.high);
    const root = document.documentElement;
    const frozen = reducedMotionActive();
    const scale = frozen ? 1 : 1 + low * .025 + mid * .018;
    const opacity = frozen ? .82 : .72 + Math.max(low, mid, high) * .24;
    root.style.setProperty("--halo-scale", String(scale));
    root.style.setProperty("--halo-opacity", String(opacity));
    [["halo-voice-low", low, 1.5], ["halo-voice-mid", mid, 2.1], ["halo-voice-high", high, 2.8]].forEach(([id, value, warp]) => {
      const ring = document.getElementById(id);
      if (!ring) return;
      ring.style.transformBox = "fill-box";
      ring.style.transformOrigin = "center";
      ring.style.transform = frozen ? "none" : `scale(${1 + value * .018},${1 + value * warp * .006})`;
      ring.style.opacity = String(frozen ? .55 : Math.min(1, .4 + value * .6));
    });
    return Object.freeze({low, mid, high, scale, opacity, reducedMotion: frozen});
  }

  function create(audioContext, sourceNode, options = {}) {
    if (!audioContext || !sourceNode || typeof sourceNode.connect !== "function") {
      throw new TypeError("A valid AudioContext and AudioNode source are required.");
    }
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = .72;
    sourceNode.connect(analyser);
    if (options.destinationNode) analyser.connect(options.destinationNode);
    const bins = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;
    let active = false;

    function bandAverage(startRatio, endRatio) {
      const start = Math.floor(bins.length * startRatio);
      const end = Math.max(start + 1, Math.floor(bins.length * endRatio));
      let total = 0;
      for (let index = start; index < end; index += 1) total += bins[index];
      return clamp(total / (end - start) / 255);
    }

    function tick() {
      if (!active) return;
      analyser.getByteFrequencyData(bins);
      const values = applyValues({low: bandAverage(.002, .08), mid: bandAverage(.08, .32), high: bandAverage(.32, .78)});
      if (typeof options.onSample === "function") options.onSample(values);
      frame = global.requestAnimationFrame(tick);
    }

    return Object.freeze({
      analyser,
      start() { if (active) return; active = true; tick(); },
      stop() { active = false; if (frame) global.cancelAnimationFrame(frame); frame = 0; applyValues({}); }
    });
  }

  global.MAEVE_HALO_ANALYZER = Object.freeze({create, applyValues, reducedMotionActive});
})(globalThis);
