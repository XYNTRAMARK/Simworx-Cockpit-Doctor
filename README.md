# Simworx Cockpit Doctor v0.4

DA62 MobiFlight audit, X-Plane 12 command test bench, and **read-only before/after DataRef monitor**.

## Windows
With X-Plane 12 and the DA62 loaded, run `START_COCKPIT_DOCTOR.bat` using Python 3.

1. Click **4 Scan live X-Plane**.
2. Click **6 WATCH DATAREFS**.
3. Search for `aerobask/eng/sw_ecu_test1` and select it.
4. Click **READ INITIAL VALUE**, operate the left ECU test switch, then click **READ AFTER SWITCH**.
5. Compare the displayed values; try the same procedure for ECU test 2, starter and other supported DataRefs.

The monitor only reads X-Plane; it does **not** access physical MobiFlight inputs directly. A value that does not change does not by itself prove the hardware has failed, because the existing mapping may be broken.

**5 LIVE TEST BENCH** can activate simulator commands only after an explicit confirmation. Such tests can operate simulated aircraft systems. Test only when parked, not during flight. It does not rewrite MobiFlight mappings.

Current limitations: no automatic physical pin event capture, no automatic MobiFlight repair, and no firmware changes. Back up the working `.mfproj` and `.mfmc` separately before modifying them.
