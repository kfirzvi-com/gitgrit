#!/bin/sh
# Install the GitGrit CLI.
#
#   curl -fsSL https://gitgrit.dev/install.sh | sh
#
# Options (environment variables):
#   GITGRIT_VERSION=v1.2.3   install that release instead of the latest stable one
#   GITGRIT_CHANNEL=edge     install the edge build (main; what staging runs)
#   GITGRIT_INSTALL_DIR=dir  where to put the binary (default: ~/.local/bin)
#   GITGRIT_DOWNLOAD_BASE=url  download from this mirror of a release's files
#
# Downloads come from the GitHub releases of kfirzvi-com/gitgrit and are
# checked against the release's checksums.txt before installing.
set -eu

REPO="kfirzvi-com/gitgrit"
INSTALL_DIR="${GITGRIT_INSTALL_DIR:-$HOME/.local/bin}"

fail() { echo "gitgrit install: $*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin) os=darwin ;;
  Linux) os=linux ;;
  *) fail "unsupported OS $(uname -s). On Windows, download gitgrit_windows_amd64.zip from https://github.com/$REPO/releases" ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) fail "unsupported CPU $(uname -m)" ;;
esac
asset="gitgrit_${os}_${arch}.tar.gz"

if [ -n "${GITGRIT_DOWNLOAD_BASE:-}" ]; then
  base="${GITGRIT_DOWNLOAD_BASE%/}"
elif [ -n "${GITGRIT_VERSION:-}" ]; then
  base="https://github.com/$REPO/releases/download/$GITGRIT_VERSION"
elif [ "${GITGRIT_CHANNEL:-stable}" = "edge" ]; then
  base="https://github.com/$REPO/releases/download/edge"
elif [ "${GITGRIT_CHANNEL:-stable}" = "stable" ]; then
  # GitHub resolves "latest" to the newest non-prerelease.
  base="https://github.com/$REPO/releases/latest/download"
else
  fail "unknown GITGRIT_CHANNEL '$GITGRIT_CHANNEL' (stable or edge)"
fi

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsSL -o "$2" "$1"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q -O "$2" "$1"; }
else
  fail "needs curl or wget"
fi
if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  fail "needs sha256sum or shasum to verify the download"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading ${asset}..."
fetch "$base/$asset" "$tmp/$asset" || fail "download failed: $base/$asset"
fetch "$base/checksums.txt" "$tmp/checksums.txt" || fail "download failed: $base/checksums.txt"

want="$(awk -v f="$asset" '$2 == f { print $1 }' "$tmp/checksums.txt")"
[ -n "$want" ] || fail "checksums.txt does not list $asset"
[ "$(sha256 "$tmp/$asset")" = "$want" ] || fail "checksum mismatch for $asset; not installing"

tar -xzf "$tmp/$asset" -C "$tmp" gitgrit
mkdir -p "$INSTALL_DIR"
mv "$tmp/gitgrit" "$INSTALL_DIR/gitgrit"
chmod 755 "$INSTALL_DIR/gitgrit"

echo "Installed $("$INSTALL_DIR/gitgrit" --version) to $INSTALL_DIR/gitgrit"
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) echo "Add it to your PATH:  export PATH=\"$INSTALL_DIR:\$PATH\"" ;;
esac
echo "Next: gitgrit auth login"
