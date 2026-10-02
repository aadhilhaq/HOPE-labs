#!/usr/bin/env bash
# The gate before a push: the selftest the release build runs, then every test here.
#
#     srun -p cpu -c 4 -t 20 bash tests/run_all.sh
#
# Each test is a script: 0 passes, anything else fails with its own output attached.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
failed=0
run() {
  local name=$1; shift
  local out
  if out=$("$@" 2>&1); then
    printf 'ok    %s\n' "$name"
  else
    printf 'FAIL  %s\n%s\n' "$name" "$out" | sed 's/^/      /;1s/^      //'
    failed=$((failed + 1))
  fi
}
run "selftest" "$PY" -m hope_labs --selftest
for t in tests/test_*.py; do
  run "$(basename "$t" .py)" "$PY" "$t"
done
echo
if [ "$failed" -eq 0 ]; then echo "ALL PASSED"; else echo "$failed FAILED"; exit 1; fi
