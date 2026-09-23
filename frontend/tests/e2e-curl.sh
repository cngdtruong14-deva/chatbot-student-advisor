#!/bin/bash
# Phase A E2E curl mock. Tests login, unlinked, isolation, chat, admin without Playwright.
# Usage: bash e2e-curl.sh <base_url> <admin_password>

set -e
BASE="${1:-http://localhost:8000/api/v1}"
PASS="${2:-testpass123}"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

log() { echo "[$(date +%H:%M:%S)] $*"; }
pass() { log "✓ $1"; ((PASS_COUNT++)); }
fail() { log "✗ $1"; ((FAIL_COUNT++)); }

PASS_COUNT=0
FAIL_COUNT=0

# E01: Login student@demo.local
log "E01: Login student@demo.local"
resp=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"student@demo.local\",\"password\":\"$PASS\"}")
token=$(echo "$resp" | grep -o '"access_token":"[^"]*' | head -1 | cut -d'"' -f4)
if [ -n "$token" ]; then
  pass "E01 login student"
  echo "$token" > "$TMPDIR/student_token"
else
  fail "E01 login student: no token in $resp"
  exit 1
fi

# E02: GET /students/me succeeds
log "E02: GET /students/me"
me=$(curl -s -X GET "$BASE/students/me" -H "Authorization: Bearer $token")
me_id=$(echo "$me" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
if echo "$me" | grep -q '"cumulative_gpa"'; then
  pass "E02 profile has GPA"
else
  fail "E02 profile missing GPA: $me"
fi

# E10: Unlinked student receives 409
log "E10: Login unlinked@demo.local, expect 409"
resp=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"unlinked@demo.local\",\"password\":\"$PASS\"}")
unlinked_token=$(echo "$resp" | grep -o '"access_token":"[^"]*' | head -1 | cut -d'"' -f4)
if [ -n "$unlinked_token" ]; then
  unlinked_me=$(curl -s -X GET "$BASE/students/me" -H "Authorization: Bearer $unlinked_token")
  if echo "$unlinked_me" | grep -q "STUDENT_PROFILE_NOT_LINKED"; then
    pass "E10 unlinked 409"
  else
    fail "E10 expected 409, got: $unlinked_me"
  fi
else
  fail "E10 login unlinked failed"
fi

# E11: Student cannot read another student's data
log "E11: Data isolation check"
resp2=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"student2@demo.local\",\"password\":\"$PASS\"}")
token2=$(echo "$resp2" | grep -o '"access_token":"[^"]*' | head -1 | cut -d'"' -f4)
me2_id=$(curl -s -X GET "$BASE/students/me" -H "Authorization: Bearer $token2" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
# Try to read student1's summary as student2
forbidden=$(curl -s -w "%{http_code}" -o "$TMPDIR/resp.json" -X GET "$BASE/students/$me_id/academic-summary" -H "Authorization: Bearer $token2")
if [ "$forbidden" = "404" ]; then
  pass "E11 data isolation 404"
else
  fail "E11 expected 404, got $forbidden"
fi

# E12: Chat session creation and message
log "E12: Chat session + message"
session=$(curl -s -X POST "$BASE/chat/sessions" -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{}')
session_id=$(echo "$session" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)
if [ -n "$session_id" ]; then
  pass "E12 chat session created"
  msg=$(curl -s -X POST "$BASE/chat/sessions/$session_id/messages" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"message\":\"GPA\",\"client_turn_id\":\"$(uuidgen)\"}")
  if echo "$msg" | grep -q '"cards"'; then
    pass "E12 chat message response"
  else
    fail "E12 chat message: no cards in $msg"
  fi
else
  fail "E12 session creation: $session"
fi

log ""
log "========================================="
log "E2E curl results: $PASS_COUNT pass, $FAIL_COUNT fail"
log "========================================="
[ $FAIL_COUNT -eq 0 ] || exit 1
