"""GitHub star count for the header repo badge, fetched at build time.

Material's source component fetches the repo facts from api.github.com in the
visitor's browser on every page, which sends each visitor's IP address to
GitHub before any consent. Fetching once here and rendering static HTML
(overrides/partials/header.html) keeps page views free of third-party
requests.

Sets config.extra.github_stars to the count, or None when GitHub can't be
reached: the badge then shows the icon alone and the build carries on.
Set GITHUB_TOKEN to lift the anonymous API rate limit, as for whats_new.py.
"""

import json
import logging
import os
import urllib.request

log = logging.getLogger("mkdocs.hooks.repo_stars")

REPO = "kfirzvi-com/gitgrit"
REPO_API = f"https://api.github.com/repos/{REPO}"


def on_config(config):
    config.extra["github_stars"] = _fetch_stars()
    return config


def _fetch_stars() -> int | None:
    request = urllib.request.Request(REPO_API, headers={"Accept": "application/vnd.github+json"})
    if token := os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(json.load(response)["stargazers_count"])
    except Exception as error:  # network, rate limit, or a changed payload
        log.warning("GitHub star count unavailable, badge shows the icon only: %s", error)
        return None
