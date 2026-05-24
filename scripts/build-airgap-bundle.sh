#!/usr/bin/env bash
# Build a self-contained air-gap installation bundle for GitGrit.
#
# Run on an internet-connected machine. Produces:
#   gitgrit-bundle-${TAG}.tar  — docker save of all required images
#   gitgrit-install-${TAG}.tgz — bundle + compose file + env template + docs
#
# Ship the .tgz to the air-gap host via whatever approved channel. The
# operator unpacks it, runs `docker load`, fills .env, and brings the stack
# up. The bundle includes site/docs/self-hosting/*.md so operators have
# the install runbook locally; the published version lives at
# https://gitgrit.dev/self-hosting/.
#
# Usage:
#   scripts/build-airgap-bundle.sh [TAG]
#
# Environment variables:
#   OUT_DIR        Output directory (default: repo root).
#   ALLOW_DIRTY=1  Bundle even when the working tree has uncommitted or
#                  staged changes. The image's GIT_SHA gets a "-dirty"
#                  suffix so the bundle is still traceable. Default: refuse
#                  to build a non-reproducible bundle.
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
command -v git >/dev/null 2>&1 || {
    echo "git not found in PATH (needed to stamp the image with HEAD)" >&2; exit 1;
}
for f in docker-compose.full.yaml .env.example \
         site/docs/self-hosting/index.md \
         site/docs/self-hosting/installation.md \
         site/docs/self-hosting/operations.md \
         sandbox_image/Dockerfile Dockerfile; do
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

# Stamp HEAD into the image so operators can prove what they're shipping —
# previously the build produced an unlabelled image and a stale source tree
# silently shipped (the airgap_smoketest command was added on a commit later
# than the image's snapshot, and the bundled image was missing it).
GIT_SHA="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
GIT_TAG="$(git -C "${REPO_ROOT}" describe --tags --exact-match HEAD 2>/dev/null || true)"
# Untracked files are intentionally not checked — leftover artifacts under
# sandbox_image/ or stray .env.* files are routine and shouldn't block a
# release build. Only committed/staged divergence from HEAD matters.
if ! git -C "${REPO_ROOT}" diff --quiet HEAD -- || \
   ! git -C "${REPO_ROOT}" diff --cached --quiet HEAD --; then
    if [ "${ALLOW_DIRTY:-}" = "1" ]; then
        echo "warning: working tree is dirty — bundling anyway because ALLOW_DIRTY=1"
        GIT_SHA="${GIT_SHA}-dirty"
    else
        echo "error: working tree is dirty (uncommitted or staged changes)." >&2
        echo "       The bundle would not be reproducible from ${GIT_SHA}." >&2
        echo "       Commit/stash first, or re-run with ALLOW_DIRTY=1." >&2
        exit 1
    fi
fi
echo "→ Bundle source: HEAD=${GIT_SHA}${GIT_TAG:+ (tag: ${GIT_TAG})}"

echo "→ Building gitgrit-app:${TAG}"
docker build \
    --build-arg "GIT_SHA=${GIT_SHA}" \
    --build-arg "GIT_TAG=${GIT_TAG}" \
    -t "gitgrit-app:${TAG}" \
    "${REPO_ROOT}"

# Sanity-check the SHA actually landed in the image. The Dockerfile places
# `ARG GIT_SHA` after `COPY . .`, so a stale cache cannot skip stamping a
# new SHA — but a future Dockerfile reorder could regress that, and this
# check is the cheapest insurance against it. Anchored to the JSON-quoted
# env value so a prefix collision (GIT_SHA=abc matching GIT_SHA=abcde) can't
# false-pass.
if ! docker image inspect "gitgrit-app:${TAG}" \
    --format '{{json .Config.Env}}' | grep -qE "\"GIT_SHA=${GIT_SHA}\""; then
    echo "error: gitgrit-app:${TAG} was built but does not carry GIT_SHA=${GIT_SHA}." >&2
    echo "       Most likely you ran this against the wrong source tree, or the" >&2
    echo "       Dockerfile no longer applies the GIT_SHA build-arg. Compare" >&2
    echo "       'docker image inspect gitgrit-app:${TAG} --format \"{{.Config.Env}}\"'" >&2
    echo "       against the expected SHA before shipping the bundle." >&2
    exit 1
fi

echo "→ Building gitgrit-sandbox:${TAG}"
docker build \
    --build-arg "GIT_SHA=${GIT_SHA}" \
    --build-arg "GIT_TAG=${GIT_TAG}" \
    -t "gitgrit-sandbox:${TAG}" \
    "${REPO_ROOT}/sandbox_image"
if ! docker image inspect "gitgrit-sandbox:${TAG}" \
    --format '{{json .Config.Env}}' | grep -qE "\"GIT_SHA=${GIT_SHA}\""; then
    echo "error: gitgrit-sandbox:${TAG} was built but does not carry GIT_SHA=${GIT_SHA}." >&2
    echo "       See the app-image stamp error above for diagnosis steps." >&2
    exit 1
fi

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
cp "${REPO_ROOT}/docker-compose.full.yaml" "${STAGE}/"
cp "${REPO_ROOT}/.env.example" "${STAGE}/"
# Ship the three self-hosting tutorial pages alongside the bundle so the
# operator has the runbook on-host without internet access. The published
# version (rendered HTML) lives at https://gitgrit.dev/self-hosting/.
mkdir -p "${STAGE}/docs/self-hosting"
cp "${REPO_ROOT}/site/docs/self-hosting/index.md"        "${STAGE}/docs/self-hosting/"
cp "${REPO_ROOT}/site/docs/self-hosting/installation.md" "${STAGE}/docs/self-hosting/"
cp "${REPO_ROOT}/site/docs/self-hosting/operations.md"   "${STAGE}/docs/self-hosting/"

tar czf "${INSTALL_TGZ}" -C "${STAGE}" .

# Note the bare bundle tar is also kept alongside the .tgz in case the
# operator wants to docker-load directly without unpacking the wrapper.

echo
echo "Bundle ready:"
du -h "${INSTALL_TGZ}" "${BUNDLE_TAR}" 2>/dev/null | sed 's/^/  /'
echo
echo "Transfer the .tgz to the air-gap host."
echo "Install runbook: docs/self-hosting/installation.md (inside the bundle),"
echo "or https://gitgrit.dev/self-hosting/installation/ if you have web access."
