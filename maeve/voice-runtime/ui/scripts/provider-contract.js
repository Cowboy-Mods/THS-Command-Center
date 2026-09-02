"use strict";

globalThis.MAEVE_PROVIDER_CONTRACT = Object.freeze({
  states: Object.freeze(["UNAVAILABLE", "READY", "GENERATING", "SPEAKING", "FALLBACK", "ERROR"]),
  currentState: "UNAVAILABLE",
  credentialAdapters: Object.freeze({
    windows: "NOT IMPLEMENTED — PLATFORM ADAPTER REQUIRED",
    raspberryPi: "NOT IMPLEMENTED — PLATFORM ADAPTER REQUIRED"
  })
});
