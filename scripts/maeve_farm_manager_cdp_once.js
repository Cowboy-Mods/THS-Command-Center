"use strict";

const [debugUrl, timeoutText] = process.argv.slice(2);
const timeoutMs = Math.max(1000, Number(timeoutText || 30000));
if (!/^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d+$/.test(debugUrl || "")) process.exit(2);

function clean(raw) {
  if (!raw || !Array.isArray(raw.devices) || raw.devices.length !== 1) throw new Error("device_count");
  const device = raw.devices[0] || {};
  const report = device.report_status || {};
  const keys = ["gcode_state", "subtask_name", "gcode_file", "mc_percent", "mc_remaining_time",
    "layer_num", "total_layer_num", "nozzle_temper", "nozzle_target_temper", "bed_temper",
    "bed_target_temper", "chamber_temper"];
  const safeReport = {};
  for (const key of keys) if (Object.prototype.hasOwnProperty.call(report, key)) safeReport[key] = report[key];
  if (Array.isArray(report.hms) && report.hms.length) {
    const first = report.hms[0] || {};
    safeReport.hms = [{ code: first.code, attr: first.attr }];
  }
  const ams = report.ams && typeof report.ams === "object" ? report.ams : null;
  if (ams && Array.isArray(ams.ams)) {
    safeReport.ams = { ams: ams.ams.slice(0, 8).map(unit => ({
      id: unit.id,
      humidity: unit.humidity,
      tray: Array.isArray(unit.tray) ? unit.tray.slice(0, 4).map(slot => ({
        id: slot.id,
        tray_type: slot.tray_type,
        tray_color: slot.tray_color,
        remain: slot.remain
      })) : []
    })) };
  }
  if (report.ip_cam && typeof report.ip_cam === "object") safeReport.ip_cam = { ipcam_dev: report.ip_cam.ipcam_dev };
  return { devices: [{ online: device.online === true, liveview_stream_status: device.liveview_stream_status, report_status: safeReport }] };
}

(async () => {
  const targets = await (await fetch(`${debugUrl}/json/list`)).json();
  const pages = targets.filter(x => x.type === "page" && x.webSocketDebuggerUrl);
  const printerPages = pages.filter(x => {
    try { return new URL(x.url).hash === "#/printers"; }
    catch { return false; }
  });
  const selected = printerPages.length === 1 ? printerPages[0] : (pages.length === 1 ? pages[0] : null);
  if (!selected) throw new Error("printer_page_count");
  const ws = new WebSocket(selected.webSocketDebuggerUrl);
  let id = 0;
  const timer = setTimeout(() => { ws.close(); process.exit(3); }, timeoutMs);
  ws.onopen = () => {
    ws.send(JSON.stringify({ id: ++id, method: "Network.enable", params: {} }));
    ws.send(JSON.stringify({ id: ++id, method: "Page.reload", params: { ignoreCache: true } }));
  };
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    const response = message?.params?.response;
    if (message.method === "Network.responseReceived" && response?.status === 200 && new URL(response.url).pathname === "/devices2") {
      const bodyId = ++id;
      ws.send(JSON.stringify({ id: bodyId, method: "Network.getResponseBody", params: { requestId: message.params.requestId } }));
      const previous = ws.onmessage;
      ws.onmessage = bodyEvent => {
        const bodyMessage = JSON.parse(bodyEvent.data);
        if (bodyMessage.id !== bodyId) return previous(bodyEvent);
        const safe = clean(JSON.parse(bodyMessage.result.body));
        clearTimeout(timer);
        process.stdout.write(JSON.stringify(safe));
        ws.close();
      };
    }
  };
  ws.onerror = () => process.exit(4);
})().catch(() => process.exit(5));
