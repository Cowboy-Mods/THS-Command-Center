# Mobile foundation, not remote access

The responsive interface remains bound to 127.0.0.1. Phone microphone access,
remote authentication, file transfer, Open Room and wake word are unavailable.
The manifest prepares standalone presentation; final icons remain unconfigured.

Future, separately authorized phases:

- A: Private home-LAN access with authenticated pairing and explicit device approval.
- B: Install the authenticated interface to the phone Home Screen as a PWA.
- C: Private authenticated encrypted away-from-home access, revocation, audit logging
  and explicit action-approval boundaries.
- D: A separately approved Raspberry Pi console and bounded file transfer.

Never directly expose Maeve's broker port to the internet. No firewall, router,
network binding or remote service is changed by this release.
