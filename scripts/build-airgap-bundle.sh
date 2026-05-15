#!/usr/bin/env bash
# Build a self-contained air-gap installation bundle for GitGrit.
#
# Run on an internet-connected machine. Produces:
#   gitgrit-bundle-${TAG}.tar  — docker save of all required images
#   gitgrit-install-${TAG}.tgz — bundle + compose file + env template + docs
#
# Ship the .tgz to the air-gap host via whatever approved channel. The
# operator unpacks it, runs `docker load`, fills .env, and brings the stack
# up. See docs/airgap.md for the full operator runbook.
#
# Usage:
#   scripts/build-airgap-bundle.sh [TAG]
#
# Example:
#   scripts/build-airgap-bundle.sh 1.0
set -euo pipefail

TAG="${1:-$(date +%Y.%m.%d)}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$REPO_ROOT}"
BUNDLE_TAR="${OUT_DIR}/gitgrit-bundle-${TAG}.tar"
INSTALL_TGZ="${OUT_DIR}/gitgrit-install-${TAG}.tgz"

# Pre-flight: fail fast before we spend 10+ min on Docker builds only to
# discover a missing file or unwritable output dir.
command -v docker >/dev/null 2>&1 || {
    echo "docker not found in PATH" >&2; exit 1;
}
for f in docker-compose.prod.yml .env.example docs/airgap.md sandbox_image/Dockerfile Dockerfile; do
    [ -e "${REPO_ROOT}/${f}" ] || {
        echo "missing required file: ${f}" >&2; exit 1;
    }
done
mkdir -p "${OUT_DIR}"
[ -w "${OUT_DIR}" ] || {
    echo "output dir not writable: ${OUT_DIR}" >&2; exit 1;
}
if [ -e "${BUNDLE_TAR}" ]; then
    echo "note: ${BUNDLE_TAR} exists and will be overwritten"
fi

echo "→ Building gitgrit-app:${TAG}"
docker build -t "gitgrit-app:${TAG}" "${REPO_ROOT}"

echo "→ Building gitgrit-sandbox:${TAG}"
docker build -t "gitgrit-sandbox:${TAG}" "${REPO_ROOT}/sandbox_image"

echo "→ Pulling postgres:15"
docker pull postgres:15

echo "→ Saving images to ${BUNDLE_TAR}"
docker save -o "${BUNDLE_TAR}" \
    "gitgrit-app:${TAG}" \
    "gitgrit-sandbox:${TAG}" \
    postgres:15

echo "→ Packing install bundle ${INSTALL_TGZ}"
# Stage in a temp dir so the tar has clean top-level names (no path leakage).
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "${BUNDLE_TAR}" "${STAGE}/"
cp "${REPO_ROOT}/docker-compose.prod.yml" "${STAGE}/"
cp "${REPO_ROOT}/.env.example" "${STAGE}/"
mkdir -p "${STAGE}/docs"
cp "${REPO_ROOT}/docs/airgap.md" "${STAGE}/docs/"

tar czf "${INSTALL_TGZ}" -C "${STAGE}" .

# Note the bare bundle tar is also kept alongside the .tgz in case the
# operator wants to docker-load directly without unpacking the wrapper.

echo
echo "Bundle ready:"
du -h "${INSTALL_TGZ}" "${BUNDLE_TAR}" 2>/dev/null | sed 's/^/  /'
echo
echo "Transfer the .tgz to the air-gap host. See docs/airgap.md for next steps."
