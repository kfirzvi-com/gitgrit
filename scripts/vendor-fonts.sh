#!/usr/bin/env bash
# Vendor Google Fonts locally for air-gapped deployments.
#
# Downloads the DM Sans + JetBrains Mono CSS that base.html references over
# the wire today, then downloads every .woff2 file the CSS points at and
# rewrites the @font-face src URLs to {% static %} paths so they resolve
# inside the air-gap container.
#
# Run once on an internet-connected machine; commit the produced files to
# the repo. The air-gap build picks them up via collectstatic.
#
# Output:
#   app/static/app/vendor/fonts/fonts.css   — combined stylesheet
#   app/static/app/vendor/fonts/*.woff2     — vendored font files
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/app/static/app/vendor/fonts"
CSS_URL="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300..700;1,9..40,300..700&family=JetBrains+Mono:wght@400;500&display=swap"
# Google Fonts serves a slimmer woff2-only stylesheet when the User-Agent
# advertises modern-browser support. Anything containing "Firefox" works.
UA="Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"

command -v curl >/dev/null 2>&1 || {
    echo "curl not found in PATH" >&2; exit 1;
}

mkdir -p "${OUT_DIR}"
# Clear stale woff2 files so this dir always reflects the current CSS
# exactly — if Google drops a variant next year, old hashed files would
# otherwise linger and get committed.
rm -f "${OUT_DIR}"/*.woff2 "${OUT_DIR}/fonts.css"

echo "→ Fetching fonts.css from Google"
RAW_CSS="$(curl -fsSL -A "${UA}" "${CSS_URL}")"

# Extract every woff2 URL the CSS references. Each appears inside
# `src: url(https://fonts.gstatic.com/...woff2) format('woff2')`.
WOFF_URLS="$(printf '%s\n' "${RAW_CSS}" | grep -oE 'https://fonts\.gstatic\.com/[^)]+\.woff2')"
[ -n "${WOFF_URLS}" ] || {
    echo "no woff2 URLs found in CSS — Google may have changed the format" >&2
    exit 1
}

# Walk each URL, download to OUT_DIR using its basename, and rewrite the
# CSS so the src points at the Django static path instead.
REWRITTEN_CSS="${RAW_CSS}"
while IFS= read -r url; do
    fname="$(basename "${url}")"
    echo "  ${fname}"
    curl -fsSL -A "${UA}" -o "${OUT_DIR}/${fname}" "${url}"
    # The CSS shipped at runtime is loaded via {% static %}, so a relative
    # URL works — the woff2 file sits in the same dir as fonts.css.
    REWRITTEN_CSS="${REWRITTEN_CSS//${url}/${fname}}"
done <<< "${WOFF_URLS}"

printf '%s' "${REWRITTEN_CSS}" > "${OUT_DIR}/fonts.css"

# Sanity-check: an HTML error page that somehow came back with status 200
# would have zero @font-face blocks. Real Google CSS has one per variant.
font_face_count="$(grep -c '@font-face' "${OUT_DIR}/fonts.css" || true)"
[ "${font_face_count}" -ge 2 ] || {
    echo "fonts.css contains only ${font_face_count} @font-face blocks — looks wrong" >&2
    exit 1
}

echo
echo "Vendored to ${OUT_DIR}:"
ls -1 "${OUT_DIR}" | sed 's/^/  /'
echo
echo "Commit these files to the repo. The air-gap container picks them up"
echo "via collectstatic — no further wiring needed (base.html already points"
echo "at {% static 'app/vendor/fonts/fonts.css' %} when AIRGAPPED=True)."
