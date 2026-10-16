# Clean-state judge-setup test (16 Oct 2026)

1. `bash demo/stop.sh` followed by `bash demo/launch.sh`, exactly as documented. Transcript: `launch_transcript.txt`, ending in READY.
2. `python console/tests/test_console_integration.py`: 18/18 OK. Transcript: `integration_transcript.txt`; results in `console/tests/runs/20261016T183321/results.json`.
3. `scenario_runs/`: every live journey transcript from that run, written by the console with real PEP results, control-plane decisions and tool-server effects.
   `s1-2-*` is an **intended FAIL**. It is run while the control plane is in owner recovery mode, and the test asserts that the read is held (APPROVAL_REQUIRED). `s1-3` passes after the owner acknowledgement.
