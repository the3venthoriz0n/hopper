#!/bin/bash
# Security Testing Script for Hopper API

BASE_URL="${1:-http://localhost:8000}"
echo "Testing API security at: $BASE_URL"
echo "=================================="

# Test 1: Session Validation
echo -e "\n[TEST 1] Session Validation"
echo "Testing endpoint without session..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/destinations")
if [ "$RESPONSE" = "200" ]; then
    echo "❌ FAIL: Endpoint accessible without session"
else
    echo "✅ PASS: Endpoint requires session (got $RESPONSE)"
fi

# Test 2: CSRF Protection
echo -e "\n[TEST 2] CSRF Protection"
echo "Testing POST without CSRF token..."
# Note: This requires a valid session_id - you'll need to get one first
echo "⚠️  Manual test required: POST to /api/destinations/youtube/toggle without X-CSRF-Token header"

# Test 3: Origin Validation
echo -e "\n[TEST 3] Origin Validation"
echo "Testing with invalid origin..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$BASE_URL/api/destinations/youtube/toggle" \
    -H "Origin: https://evil-site.com" \
    -H "Cookie: session_id=test")
if [ "$RESPONSE" = "403" ]; then
    echo "✅ PASS: Invalid origin rejected"
else
    echo "⚠️  Got response code: $RESPONSE (may need valid session/CSRF)"
fi

# Test 4: Rate Limiting
echo -e "\n[TEST 4] Rate Limiting"
echo "Sending 25 rapid requests..."
RATE_LIMITED=0
for i in {1..25}; do
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X GET "$BASE_URL/api/destinations" \
        -H "Cookie: session_id=test_rate_limit_$$")
    if [ "$RESPONSE" = "429" ]; then
        RATE_LIMITED=1
        echo "✅ Rate limited at request $i (got 429)"
        break
    fi
done
if [ "$RATE_LIMITED" = "0" ]; then
    echo "⚠️  No rate limiting detected (may need valid session)"
fi

echo -e "\n=================================="
echo "Security tests complete!"
echo "Note: Some tests require valid session cookies and CSRF tokens"
echo "Check backend logs for detailed API access logging"

