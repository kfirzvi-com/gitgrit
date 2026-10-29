"""MkDocs hook: generate the What's New page from GitHub releases.

The page is built from the published `vX.Y.Z` releases of the gitgrit repo
(drafts and the rolling `edge` prerelease are skipped). It is generated at
build time so it is plain HTML: searchable, indexable, no client-side API
calls. A deploy therefore shows the releases that existed when it was built.

Set GITHUB_TOKEN to lift the anonymous API rate limit (60 requests/hour per
IP, which shared CI runners can exhaust). If GitHub can't be reached the build
still succeeds and the page links to the releases on GitHub instead.
"""

import json
import logging
import os
import re
import urllib.request
from datetime import datetime

from mkdocs.structure.files import File

REPO = "kfirzvi-com/gitgrit"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=100"
RELEASES_URL = f"https://github.com/{REPO}/releases"
PAGE_PATH = "whats-new.md"

STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# A line of GitHub's generated notes: "* Title by @user in https://.../pull/123"
GENERATED_ITEM = re.compile(
    r"^\* (?P<title>.+) by @\S+ in (?P<url>https://github\.com/\S+/pull/(?P<number>\d+))$"
)
FULL_CHANGELOG = re.compile(r"^\*\*Full Changelog\*\*: (?P<url>\S+)$")
# Sections of generated notes that are about the repo, not the product.
SKIPPED_SECTIONS = {"What's Changed", "New Contributors"}

log = logging.getLogger("mkdocs.hooks.whats_new")

# mkdocs serve rebuilds on every save; fetch once per process.
_releases: list[dict] | None = None


def on_files(files, config):
    files.append(File.generated(config, PAGE_PATH, content=_render(_fetch_releases())))
    return files


def _fetch_releases() -> list[dict]:
    global _releases
    if _releases is not None:
        return _releases

    request = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    if token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            releases = json.load(response)
    except Exception as exc:  # noqa: BLE001 — a missing changelog must not fail the docs build
        log.warning("What's New: could not fetch releases from GitHub (%s)", exc)
        releases = []

    _releases = [
        r for r in releases
        if not r["draft"] and not r["prerelease"] and STABLE_TAG.match(r["tag_name"])
    ]
    return _releases


def _render(releases: list[dict]) -> str:
    lines = [
        "---",
        "title: What's New",
        "description: Every GitGrit release, newest first.",
        "---",
        "",
        "# What's New",
        "",
        f"Every GitGrit release, newest first. Release assets and the full history are on "
        f"[GitHub]({RELEASES_URL}){{target=_blank rel=noopener}}.",
        "",
    ]
    if not releases:
        lines.append(f"The changelog couldn't be loaded. See the [releases on GitHub]({RELEASES_URL}).")
    for release in releases:
        lines += _render_release(release)
    return "\n".join(lines) + "\n"


def _render_release(release: dict) -> list[str]:
    published = datetime.fromisoformat(release["published_at"])
    return [
        f"## {release['tag_name']} {{ #{release['tag_name'].replace('.', '-')} }}",
        "",
        f'<p class="gg-release__meta">{published:%B} {published.day}, {published:%Y} · '
        f'<a href="{release["html_url"]}" target="_blank" rel="noopener">Release notes on GitHub</a></p>',
        "",
        *_render_body(release["body"] or ""),
        "",
    ]


def _render_body(body: str) -> list[str]:
    """Fit a release body under the release's own heading.

    Headings drop one level, generated PR lines become "Title (#123)", and the
    repo-housekeeping sections of GitHub's generated notes are removed.
    """
    lines: list[str] = []
    in_fence = False
    skipping = False
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#"):
            heading = line.lstrip("#").strip()
            skipping = heading == "New Contributors"
            if heading in SKIPPED_SECTIONS:
                continue
            line = "#" + line
        elif not in_fence and (match := GENERATED_ITEM.match(line)):
            line = f"- {match['title']} ([#{match['number']}]({match['url']}))"
        elif not in_fence and FULL_CHANGELOG.match(line):
            continue
        if not skipping:
            lines.append(line)
    return lines
