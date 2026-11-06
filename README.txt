SIMWORX COCKPIT DOCTOR v0.3 — Live Test Bench
Run START_COCKPIT_DOCTOR.bat with Python installed.
1. Start X-Plane with DA62 loaded.
2. Click 4 Scan live X-Plane.
3. Click 5 LIVE TEST BENCH.
4. Search for a command, select it, and click TEST SELECTED COMMAND.
5. Confirm to send a single short command. Observe cockpit behaviour.

Only explicitly confirmed command tests send an action to X-Plane. No MobiFlight or aircraft files are modified. The simulator may change state when a command is executed. No automatic reset is possible for arbitrary commands. Use a parked aircraft and avoid testing flight-critical controls in flight.

API: http://127.0.0.1:8086/api/v2/command/{id}/activate
