#!/bin/sh
# The realm's battery, against a live appliance with this realm installed. Last line on success is
# exactly `ALL CHECKS PASS`; any failure exits non-zero.
#
#   APPLIANCE=http://127.0.0.1:11043 AUTH=user:pass sh tests/verify.sh
#
# Keyless: every figure is stored in the realm, and the ground truth (tests/expected.json) was
# computed straight from Cricsheet's raw files by tests/ground_truth.py. Also accepts
# APPLIANCE_URL with EMBABEL_USER and EMBABEL_PASSWORD, which the two scripts below read.
#
#   L1  tests/views.smoke.mjs  every view answers BY NAME on its defaults, plus cases that must
#                              carry particular rows and cases that must be empty
#   L2  tests/verify.py        the views' figures equal the ground truth, exactly
#
# No L3: nothing is fetched, so there is no source call to count.
cd "$(dirname "$0")/.." || exit 2
APPLIANCE_URL=${APPLIANCE_URL:-${APPLIANCE:-http://127.0.0.1:11043}}
if [ -n "${AUTH:-}" ]; then
  EMBABEL_USER=${EMBABEL_USER:-${AUTH%%:*}}
  EMBABEL_PASSWORD=${EMBABEL_PASSWORD:-${AUTH#*:}}
fi
: "${EMBABEL_USER:?set AUTH (user:pass), or EMBABEL_USER and EMBABEL_PASSWORD}"
: "${EMBABEL_PASSWORD:?set AUTH (user:pass), or EMBABEL_USER and EMBABEL_PASSWORD}"
export APPLIANCE_URL EMBABEL_USER EMBABEL_PASSWORD

fail=0
echo "== L1: every view, by name"
node tests/views.smoke.mjs || fail=1
echo "== L2: the figures, against Cricsheet's own"
python3 tests/verify.py "$APPLIANCE_URL" || fail=1

[ $fail = 0 ] && echo "ALL CHECKS PASS" || { echo "CHECKS FAILED"; exit 1; }
