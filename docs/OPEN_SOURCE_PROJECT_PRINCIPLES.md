# Open-Source Project Principles

> **Built for my shop first, but not trapped inside my shop.**

THS Command Center can be deeply customized for Cowboy's THS installation while its shared core remains shop-neutral. The project must let other users operate independently with their own branding, equipment, terminology, workflows, and layouts.

## Implemented at this checkpoint

- The core is local-first and self-hosting remains fully functional.
- Inventory data uses a shop-neutral data model with configurable categories, item types, attributes, locations, equipment, and controlled inventory actions.
- Numbered migrations, isolated SQLite databases, and ignored runtime files keep user installations and operational data separate from source control.
- Controlled inventory writes go through the Inventory Action Service and retain auditable history.
- Current printer status is explicitly labeled by source and freshness. The seeded THS Printer / Bambu Lab P1S record is manual and stale; no live job is asserted.

These implemented foundations do not mean every configuration surface or integration listed below already has a user interface.

## Planned principles

- Shop name, branding, printers, AMS units, alerts, workflows, terminology, and layouts must be configuration rather than required hard-coded THS values.
- Other users may operate independently with their own branding and equipment.
- Cloud services remain optional.
- An official phone application may act as a client, but it must not depend on secret functionality unavailable to other clients.
- Community applications and plugins are allowed.
- Official, community, and unverified integrations must be clearly labeled.
- Third-party applications must not imply official THS endorsement.
- User installations, databases, credentials, and configurations must remain isolated.
- Plugins must not weaken the core data model or bypass controlled inventory writes.
- Bambu Lab, Prusa, Klipper, OctoPrint, and future printer support should use neutral integration boundaries.

## Deferred and not completed

- Progressive Web App behavior is not completed.
- An official iPhone application is not completed.
- Cloud hosting or cloud synchronization is not completed.
- Live Bambu Lab printer or AMS integration is not completed.
- A general plugin runtime and integration-verification program are not completed.

## Project identity and legal boundary

THS and Top Hat Syndicate identify Cowboy's shop and its customized installation. This checkpoint does not claim that THS or its logos are registered trademarks. Third-party projects must describe their relationship accurately and must not imply official THS endorsement.

This checkpoint does not select or change the software license.
