#!/bin/bash
# _verify_playwright_env.sh — ensure Playwright + Chromium are installed (Phase 8, R-6)
set -euo pipefail

echo -n "Playwright package ... "
if python -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "OK"
else
    echo "FAIL — run: npm install && npx playwright install chromium"
    exit 1
fi

echo -n "Chromium browser ... "
if python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    b.close()
    print('OK')
" 2>/dev/null; then
    :
else
    echo "FAIL — run: npx playwright install chromium"
    exit 1
fi

echo "Playwright environment verified"
exit 0
