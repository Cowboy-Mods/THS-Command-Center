"use strict";

(function publishHaloAnalyzer(global) {
  const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));

  function reducedMotionActive() {
    return global.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function applyValues(values = {}, source = "none") {
    const low = clamp(values.low);
    const mid = clamp(values.mid);
    const high = clamp(values.high);
    const root = document.documentElement;
    const frozen = reducedMotionActive();
    global.MAEVE_VOICE_DISPLAY?.apply({low, mid, high}, source);
    const scale = frozen ? 1 : 1 + low * .025 + mid * .018;
    const opacity = frozen ? .82 : .72 + Math.max(low, mid, high) * .24;
    root.style.setProperty("--halo-scale", String(scale));
    root.style.setProperty("--halo-opacity", String(opacity));
    const radialWavePath=(radius,amplitude,phase)=>{const points=120,segments=[];for(let index=0;index<=points;index+=1){const angle=Math.PI*2*index/points,modulated=radius+Math.sin(angle*8+phase)*amplitude+Math.sin(angle*13-phase)*amplitude*.32,x=500+Math.cos(angle)*modulated,y=500+Math.sin(angle)*modulated;segments.push(`${index?"L":"M"}${x.toFixed(2)} ${y.toFixed(2)}`);}return `${segments.join(" ")} Z`;};
    [["halo-wave-low",390,low,0],["halo-wave-mid",405,mid,1.7],["halo-wave-high",375,high,3.1]].forEach(([id,radius,value,phase])=>{const wave=document.getElementById(id);if(!wave)return;const amplitude=frozen?0:2+value*34;wave.setAttribute("d",radialWavePath(radius,amplitude,phase));wave.style.opacity=String(frozen?.44:.44+value*.5);});
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
      const values = applyValues({low: bandAverage(.002, .08), mid: bandAverage(.08, .32), high: bandAverage(.32, .78)}, "playback");
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
  applyValues({});
})(globalThis);
