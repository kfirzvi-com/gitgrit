#!/usr/bin/env bash
# Vendor the app's front-end libraries (DaisyUI, Tailwind browser build, HTMX).
#
# base.html always serves these local copies, never a CDN: a page view then
# sends the visitor's IP address to no third party. Pinned versions also mean
# a CDN release can't change the UI under us. Fonts: scripts/vendor-fonts.sh.
#
# To upgrade, bump a version below, run this on an internet-connected machine,
# check the app, and commit the produced files.
#
# Output (app/static/app/vendor/):
#   daisyui.css, daisyui-themes.css, tailwindcss-browser.js, htmx.js
set -euo pipefail

DAISYUI=5.8.3
TAILWIND_BROWSER=4.3.5
HTMX=2.0.11

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/app/static/app/vendor"
CDN="https://cdn.jsdelivr.net/npm"

fetch() {  # url file
    curl -fsSL "$1" -o "${OUT_DIR}/$2.tmp" && mv "${OUT_DIR}/$2.tmp" "${OUT_DIR}/$2"
    echo "  $2 <- $1"
}

mkdir -p "${OUT_DIR}"
fetch "${CDN}/daisyui@${DAISYUI}/daisyui.css" daisyui.css
fetch "${CDN}/daisyui@${DAISYUI}/themes.css" daisyui-themes.css
fetch "${CDN}/@tailwindcss/browser@${TAILWIND_BROWSER}/dist/index.global.min.js" tailwindcss-browser.js
fetch "${CDN}/htmx.org@${HTMX}/dist/htmx.min.js" htmx.js
