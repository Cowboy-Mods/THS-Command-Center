# Maeve Local Console Foundation

Maeve's local console is a loopback-only, monitoring-only command-center shell.

- URL: `http://127.0.0.1:48176/`
- Listener: `127.0.0.1` only
- HTTP methods: GET and HEAD only
- Printer controls: none
- MQTT: parked / firmware blocked
- Camera: viewer-driven TLS/JPEG adapter with one shared connection maximum
- Inventory: read-only status and local links
- Remote access: not exposed

The browser never receives credentials, the printer address, or a direct printer
socket. The server loads the access code from the current-user DPAPI record only
when an active local viewer requires the camera. One cached frame is shared by all
local tabs. The camera releases after 20 seconds without viewer activity and is
released before the verified Bambu Studio executable is launched.

Current print fields remain `NOT REPORTED` until a separately verified telemetry
source exists. MQTT remains parked and no printer-control API exists.

## Windows lifecycle

- `Start Maeve Console.cmd` starts one verified process and confirms ownership of
  `127.0.0.1:48176`.
- `Stop Maeve Console.cmd` signals the adapter to close first, then stops only the
  verified Maeve process and confirms the port is released.
- `Open Maeve Console.cmd` starts the service if needed and opens the loopback URL.
- Current-user startup uses `Maeve Command Console Startup.lnk` in the Windows
  Startup folder. Removing that shortcut reverses automatic startup.
- Desktop access uses `MAEVE COMMAND CONSOLE.lnk`.
