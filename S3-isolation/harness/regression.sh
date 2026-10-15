#!/usr/bin/env bash
# S3 / AM11 regression suite. Every assertion is recorded in <run>/regression_summary.txt.
#   R1 checker mutation tests: 24 non-compliant models rejected, the canonical model accepted
#   R2 fail-closed deploy: misspelled-key and missing-isolated profiles REFUSED, 0 containers created
#   R3 baseline regression fixture (compose.yaml): T3 must still FAIL (T3e/T3f/T3g); runtime checker must flag it
#   R4 canonical profile (compose.cell.yaml) through the gate: full S3 suite, 0 FAIL, 0 HARNESS-ERROR, T5 PASS
#   R5 runtime drift: attach a foreign container to a cell network -> runtime checker flags it; detach -> compliant
# Usage: bash harness/regression.sh
set -u
export PATH="/c/Users/SEBIN/AppData/Local/Programs/DockerDesktop/resources/bin:$PATH" MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
R="runs/$(date +%Y%m%dT%H%M%S)-regression"; mkdir -p "$R"
S="$R/regression_summary.txt"; FAILS=0
check() { # check <id> <description> <condition-exit-code>
  if [ "$3" -eq 0 ]; then echo "PASS  $1  $2" | tee -a "$S"; else echo "FAIL  $1  $2" | tee -a "$S"; FAILS=$((FAILS+1)); fi; }
count_ctr() { docker ps -aq --filter label=com.docker.compose.project=s3iso | wc -l; }
down_all() { local cf; for cf in compose.cell.yaml compose.yaml; do docker compose -p s3iso -f config/$cf --env-file config/.env down -v --remove-orphans >/dev/null 2>&1; done; }
{ date -u; git rev-parse HEAD 2>/dev/null; git status --short | head -20; docker version --format 'engine={{.Server.Version}}'; } > "$R/meta.txt"

# R1
python harness/test_cell_policy.py "$R/R1-checker" > "$R/R1-checker.log" 2>&1; rc=$?
tail -1 "$R/R1-checker.log" | tee -a "$S"; check R1 "checker mutation suite (exit $rc)" $rc

# R2
# Each case must be refused for the EXPECTED reason (not a checker error), with nothing created.
for case in "typo|unexpected driver_opt 'com.docker.network.bridge.gatway_mode_ipv4'" "no-isolated|gateway_mode_ipv4 = None"; do
  f="${case%%|*}"; want="${case#*|}"
  test -f "config/regression/compose.cell.$f.yaml" || { check "R2-$f" "fixture file missing" 1; continue; }
  down_all
  bash harness/deploy_cells.sh "regression/compose.cell.$f.yaml" "$R/R2-$f" > "$R/R2-$f.log" 2>&1; rc=$?
  n=$(count_ctr)
  echo "R2-$f deploy_exit=$rc containers_after=$n" >> "$S"
  [ $rc -eq 3 ] && [ "$n" -eq 0 ] && grep -qF "$want" "$R/R2-$f/cell_policy_static.json" && ! grep -q checker_error "$R/R2-$f/cell_policy_static.json"
  check "R2-$f" "deploy refused (exit 3) for the expected reason [$want], nothing created (containers=$n)" $?
done

# R3
down_all
bash harness/run_variant.sh compose.yaml baseline-regression regression-fixture > "$R/R3.log" 2>&1
B=$(sed -n 's/^RUN=//p' "$R/R3.log"); echo "R3 run: $B" >> "$S"
fails=$(python -c "import json;print(' '.join(sorted(r['id'] for r in map(json.loads,open('$B/results.jsonl')) if r['verdict']=='FAIL')))")
herr=$(grep -c '"HARNESS-ERROR"' "$B/results.jsonl")
echo "R3 FAIL set: $fails | HARNESS-ERROR: $herr" >> "$S"
[ "$fails" = "T3e-dot1-full-tcp-sweep T3f-dot1-udp111 T3g-any-ip-on-host-side" ] && [ "$herr" -eq 0 ]
check R3a "baseline reproduces exactly the T3 failure set (T3e T3f T3g), no harness errors" $?
grep -q "runtime_check_exit=3" "$B/deploy.log" && grep -q "host-side bridge" "$B/cell_policy_runtime.json" && grep -q "gateway_mode_ipv4" "$B/cell_policy_runtime.json"
check R3b "runtime checker flags the baseline (exit 3; host-bridge IPv4 + missing isolated mode)" $?

# R4
down_all
bash harness/run_variant.sh compose.cell.yaml canonical > "$R/R4.log" 2>&1
C=$(sed -n 's/^RUN=//p' "$R/R4.log"); echo "R4 run: $C" >> "$S"
grep -q "DEPLOYED: static and runtime AM11 checks passed" "$C/deploy.log"; check R4a "canonical profile passes the AM11 gate (static + runtime)" $?
python - "$C" >> "$S" <<'PY'
import json, sys
rs = [json.loads(l) for l in open(sys.argv[1] + "/results.jsonl")]
c = {}
for r in rs: c[r["verdict"]] = c.get(r["verdict"], 0) + 1
print("R4 verdict counts:", c)
PY
nf=$(grep -c '"verdict": "FAIL"' "$C/results.jsonl"); nh=$(grep -c '"HARNESS-ERROR"' "$C/results.jsonl")
t5=$(grep '"T5-gateway-reachable"' "$C/results.jsonl" | grep -c '"verdict": "PASS"')
[ "$nf" -eq 0 ] && [ "$nh" -eq 0 ] && [ "$t5" -eq 1 ]; check R4b "canonical: 0 FAIL, 0 HARNESS-ERROR, T5 approved gateway path PASS" $?

# R5 (canonical deployment is still up after R4)
python harness/cell_policy.py runtime s3iso > "$R/R5-before.json"; rc0=$?
docker network connect s3iso_cellnet_a s3iso-outside-1
python harness/cell_policy.py runtime s3iso > "$R/R5-drift.json"; rc1=$?
docker network disconnect s3iso_cellnet_a s3iso-outside-1
python harness/cell_policy.py runtime s3iso > "$R/R5-after.json"; rc2=$?
echo "R5 runtime exits before/drift/after = $rc0/$rc1/$rc2" >> "$S"
[ $rc0 -eq 0 ] && [ $rc1 -eq 3 ] && grep -q "forbidden members" "$R/R5-drift.json" && [ $rc2 -eq 0 ]
check R5 "runtime checker detects a foreign member on a cell network" $?

echo "REGRESSION: $FAILS failing assertion(s)" | tee -a "$S"
echo "RUN=$R"
exit $([ $FAILS -eq 0 ] && echo 0 || echo 1)
