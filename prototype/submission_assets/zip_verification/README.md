# Submission ZIP verification (16 Oct 2026)

- ZIP: `validation/submission/MANDATE_E4.2.1_submission.zip`, sha256 `440424ae97e155c95e8357a5c847ecf4cb9a50177acd897674f78524c7c7c81f` (1.6 MB, 203 files + MANIFEST.sha256 + README.md). Built by `demo/make_submission.py` from the source at commit 872a883 plus the packaging-script fix in the commit that adds this record.
- Extracted into a fresh scratch directory (outside the repository):
  1. `sha256sum -c MANIFEST.sha256` printed MANIFEST_OK;
  2. `bash demo/launch.sh` from the extracted `prototype/` reached READY (AM11 gates exit 0, engine E4.2.1);
  3. `python console/tests/test_console_integration.py` from the extracted copy: **18/18 OK** (`integration_from_extracted_zip.txt`, `results.json`).
- Same machine as development. This is not a second-machine or clean-machine reproduction.

## Rebuild after the optional live-LLM agent (17 Oct 2026)

- New ZIP sha256 `0085d75caa47ce770d0c205a61ba21e413bac4cb29d6c7701946377b8ee790e9` (213 files). Adds `console/llm_agent.py`, the Live LLM page and `submission_assets/live_llm_runs/`.
- Extracted copy: MANIFEST_OK. No file in the ZIP contains a Groq key (scanned).
- Base demo (no key) re-verified 18/18 on the repository stack before the rebuild (`console/tests/runs/20261017T222711`). The extracted-copy launch from 16 Oct was not repeated, because it would stop the live console running in your terminal.

## Rebuild for UI release P2 (17 Oct 2026)

- ZIP sha256 `14d71012fff38e1088cabc0f5ce77fa12941392c2369b75512e2e8e2069acef6` (219 files). Extracted copy: MANIFEST_OK. Contains `console/verify_evidence_pack.py` and `UI_RELEASE_P2.md`. No Groq key in any file.
- Base demo verified 21/21 on the repository stack (`console/tests/runs/20261017T225310`), with E2E 17/17 and 13/13.
