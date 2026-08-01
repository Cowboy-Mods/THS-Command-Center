# ED-0005: Maeve V2/V3 Enclosure and Front-Panel Hardware Direction

- Status: Accepted
- Decision date: 2026-08-01
- Scope: Maeve physical enclosure and hardware-interface planning
- Implementation status: Documentation only; this record does not claim that the enclosure, wiring, or software integration is complete

## Context

Maeve needs a stable hardware direction before detailed enclosure modeling, component-clearance work, cable routing, and bench assembly continue. Earlier concept maps are visual references, not manufacturing drawings. Their dimensions, connector positions, clearances, and internal layouts must not be treated as verified measurements.

This decision locks the V2/V3 direction while preserving a clear line between selected components, optional internal routing, and purchases that remain deferred.

## Decision

### V2 enclosure direction

V2 is the functional enclosure baseline. It will prioritize a reliable seven-inch landscape touch interface, serviceable internal access, verified component clearances, practical cooling, and clean front-panel controls. The enclosure remains a dark THS black or charcoal design with orange accents, but appearance must not override serviceability, cable bend radius, airflow, fastening, or printability.

The front panel will include:

- Two Adafruit 4052 snap-in panel-mount USB-C sockets. Each extension terminates internally in a USB-A plug.
- No front USB-A port.
- Two Adafruit 1669 speakers, one on each side of the primary interface area, with enclosure openings designed from verified speaker geometry.
- One Raspberry Pi Camera Module 3 Wide centered above the display, subject to verification of the real camera board, lens field of view, ribbon-cable routing, and mounting clearances.
- One Adafruit 1374 flat touch control in the THS skull control area. The skull is the visible touch target; it is not a protruding mechanical pushbutton.
- Voice-reactive orange lighting used as restrained status and interaction feedback, not as a substitute for readable dashboard state.
- mmWave presence sensing positioned and tuned only after its field of view, enclosure-material behavior, false-trigger risk, and workshop placement are tested.
- A ReSpeaker XVF3800 USB microphone array as the voice-input hardware direction, with final microphone opening pattern, acoustic isolation, USB routing, and placement based on the real unit.

The front face must remain touch-friendly and uncluttered. Removing the front USB-A port gives the touch control, speakers, lighting, and two USB-C ports clearer visual and physical separation.

### V3 enclosure direction

V3 will refine the accepted V2 arrangement rather than restart the enclosure concept. It may improve THS styling, speaker-hole treatment, lighting diffusion, seams, service access, mounting, airflow, cable management, and print efficiency after the V2 hardware fit and bench behavior are proven.

V3 must preserve these interface decisions unless a documented fit, safety, reliability, or availability problem requires a new decision:

- Two front Adafruit 4052 USB-C ports
- No front USB-A port
- Adafruit 1669 speakers
- Camera Module 3 Wide
- Adafruit 1374 flat skull touch control
- Voice-reactive orange lighting
- mmWave presence sensing
- ReSpeaker XVF3800 USB microphone array

## USB and powered-hub routing

The enclosure may include an internal powered USB hub when the verified USB-device count, current demand, startup behavior, cable direction, and available clearance show that one is required. The internal design must not assume that every connected device can be powered reliably from the Raspberry Pi alone.

Hub routing must:

- Keep the two front Adafruit 4052 extensions serviceable.
- Account for the ReSpeaker XVF3800 USB connection and any other internal USB devices.
- Separate USB data-path decisions from device power-budget decisions.
- Avoid tight cable bends and blocked connectors.
- Preserve access for replacement without rebuilding the complete enclosure.
- Use an independently powered hub only after its voltage, current, back-powering behavior, connector orientation, and physical dimensions are verified.

The exact internal powered-hub model is not locked by this record.

## Deferred purchases

The following products remain deferred and must not be represented as purchased, installed, or required for enclosure manufacturing dimensions:

- StarTech 10G5A2CS-USB-C-HUB — external 7-port powered desktop USB hub (5 USB-A + 2 USB-C), with 10 Gbps upstream connectivity and a 65 W power adapter
- TP-Link TL-SG1210MPE Ethernet switch

These purchases will be revisited after the complete USB-device count, power budget, Ethernet port and speed requirements, PoE usefulness, cable directions and lengths, and enclosure/bench clearances are verified. The desktop StarTech hub is an external bench-routing option; it is not automatically the internal enclosure hub.

## Verification gates before manufacturing

Before the V2 enclosure becomes a manufacturing model, the project must verify the physical hardware or authoritative mechanical drawings for:

- Display outside dimensions, active area, mounting points, connector locations, and cable exits
- Both Adafruit 4052 panel cutouts, retention tabs, cable lengths, and rear bend clearance
- Both Adafruit 1669 speaker bodies, diaphragms, mounting method, and acoustic openings
- Camera Module 3 Wide board, lens, ribbon connector, mounting, and unobstructed field of view
- Adafruit 1374 touch-control board, sensing range through the selected front material, wiring, and service access
- Lighting strip or LED hardware, diffuser space, heat, power, and controller routing
- mmWave sensor board, field of view, mounting orientation, power, and enclosure-material effects
- ReSpeaker XVF3800 board or enclosure geometry, microphones, USB connector, acoustic openings, and isolation
- Raspberry Pi, power system, cooling, internal hub if selected, wiring, fasteners, and all service clearances

Until those gates are complete, concept-image measurements remain provisional and Blender geometry remains design exploration rather than production-ready geometry.

## Boundaries

This decision does not:

- Modify production data, telemetry, inventory, or printer connectivity.
- Modify or approve any Blender enclosure file.
- Authorize purchases.
- Lock unverified manufacturing dimensions.
- Mix Financial Headquarters or private health-module data into Maeve Core hardware planning.

## Consequences

- Front-panel modeling can proceed around a stable component and control layout.
- The eliminated front USB-A opening simplifies the face and reduces competing controls.
- Voice, presence, and lighting now require an explicit USB and power-budget pass before bench assembly.
- V3 becomes a proven refinement cycle instead of an unbounded redesign.
- The powered hub and Ethernet switch remain visible future decisions without being prematurely purchased or modeled as fixed hardware.
