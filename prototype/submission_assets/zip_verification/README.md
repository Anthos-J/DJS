# Submission ZIP verification (16 Oct 2026)

- ZIP: `validation/submission/MANDATE_E4.2.1_submission.zip`, sha256 `440424ae97e155c95e8357a5c847ecf4cb9a50177acd897674f78524c7c7c81f` (1.6 MB, 203 files + MANIFEST.sha256 + README.md). Built by `demo/make_submission.py` from the source at commit 872a883 plus the packaging-script fix in the commit that adds this record.
- Extracted into a fresh scratch directory (outside the repository):
  1. `sha256sum -c MANIFEST.sha256` printed MANIFEST_OK;
  2. `bash demo/launch.sh` from the extracted `prototype/` reached READY (AM11 gates exit 0, engine E4.2.1);
  3. `python console/tests/test_console_integration.py` from the extracted copy: **18/18 OK** (`integration_from_extracted_zip.txt`, `results.json`).
- Same machine as development. This is not a second-machine or clean-machine reproduction.
