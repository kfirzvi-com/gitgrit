"""MkDocs hook: generate the What's New page from GitHub releases.

The page is built from the published `vX.Y.Z` releases of the gitgrit repo
(drafts and the rolling `edge` prerelease are skipped). It is generated at
build time so it is plain HTML: searchable, indexable, no client-side API
calls. A deploy therefore shows the releases that existed when it was built.

The notes are curated for users, not contributors: a PR that was reverted,
the revert itself, and the PRs in HIDDEN_PRS (CI, build and repo chores) are
left out. A release left with nothing to show says so instead of vanishing,
so the version list has no gaps.

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

# PRs that changed nothing a GitGrit user would notice. Reverted PRs don't
# belong here when the revert names them ("Revert ... (#165–#170)"): those
# are found on their own.
HIDDEN_PRS = {
    # CI, build and release plumbing
    63, 66, 76, 93, 148, 158,
    # Repo housekeeping
    68, 74,
    # Internal job and connection handling, no visible change
    113, 135,
    # Fixes told in implementation terms (dependency pin, agent internals, an
    # MCP endpoint since removed, a settings refactor #162 covers)
    67, 75, 146, 159,
    # Solutions pages and Book-a-consult popup, reverted by #92 (which
    # doesn't name them)
    79, 80, 81, 82, 83, 84, 85, 87, 88,
}

STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# A line of GitHub's generated notes: "* Title by @user in https://.../pull/123"
GENERATED_ITEM = re.compile(
    r"^\* (?P<title>.+) by @\S+ in (?P<url>https://github\.com/\S+/pull/(?P<number>\d+))$"
)
# "feat: ", "fix(ci): " — commit-style prefixes some PR titles carry.
CONVENTIONAL_PREFIX = re.compile(r"^[a-z]+(\([^)]*\))?: ")
# "#165", or a range "#165–#170" / "#165-#170", as a revert names its targets.
PR_REFERENCE = re.compile(r"#(\d+)(?:\s*[–-]\s*#(\d+))?")
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
    hidden = HIDDEN_PRS | _reverted_prs(releases)
    for release in releases:
        lines += _render_release(release, hidden)
    return "\n".join(lines) + "\n"


def _reverted_prs(releases: list[dict]) -> set[int]:
    """Every revert PR, and every PR a revert names, across all releases.

    A revert can ship in a later release than the PRs it undoes, so this looks
    at all of them before any release is rendered.
    """
    reverted: set[int] = set()
    for release in releases:
        for line in (release["body"] or "").splitlines():
            match = GENERATED_ITEM.match(line.strip())
            if not match or not _strip_prefix(match["title"]).lower().startswith("revert"):
                continue
            reverted.add(int(match["number"]))
            for first, last in PR_REFERENCE.findall(match["title"]):
                reverted.update(range(int(first), int(last or first) + 1))
    return reverted


def _render_release(release: dict, hidden: set[int]) -> list[str]:
    published = datetime.fromisoformat(release["published_at"])
    body = _render_body(release["body"] or "", hidden)
    if not any(line.strip() for line in body):
        body = ["Maintenance release: fixes behind the scenes, nothing new to see."]
    return [
        f"## {release['tag_name']} {{ #{release['tag_name'].replace('.', '-')} }}",
        "",
        f'<p class="gg-release__meta">{published:%B} {published.day}, {published:%Y} · '
        f'<a href="{release["html_url"]}" target="_blank" rel="noopener">Release notes on GitHub</a></p>',
        "",
        *body,
        "",
    ]


def _render_body(body: str, hidden: set[int]) -> list[str]:
    """Fit a release body under the release's own heading.

    Headings drop one level, generated PR lines become "Title (#123)" (or go,
    when hidden), and the repo-housekeeping sections of GitHub's generated
    notes are removed.
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
            if int(match["number"]) in hidden:
                continue
            line = f"- {_strip_prefix(match['title'])} ([#{match['number']}]({match['url']}))"
        elif not in_fence and FULL_CHANGELOG.match(line):
            continue
        if not skipping:
            lines.append(line)
    return lines


def _strip_prefix(title: str) -> str:
    title = CONVENTIONAL_PREFIX.sub("", title)
    return title[:1].upper() + title[1:]
