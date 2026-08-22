# Maeve Telemetry Rollback Plan

Nothing in this plan is executed automatically.

1. Stop only the future Maeve gateway process after verifying its PID, command
   line, source path, and localhost listener ownership.
2. Remove only the future OctoEverywhere container by its exact verified name.
   Do not prune Docker, delete unrelated images, remove volumes globally, or
   remove other containers.
3. Preserve the sanitized runtime state and OctoEverywhere persistent data until
   Cowboy confirms whether they are still needed.
4. Restore the timestamped `Bambu.ini` backup if the Rainmeter integration must
   be rolled back. Refresh only the Bambu skin.
5. Docker Desktop can later be uninstalled through Windows Installed Apps if it
   was used only for Maeve. Do not remove WSL distributions or Docker data until
   each exact owner and recovery need is reviewed.

Repository source, documentation, tests, staged installers, external runtime
state, and Rainmeter backups remain after a normal component stop. Production
inventory data is never part of this rollback.
