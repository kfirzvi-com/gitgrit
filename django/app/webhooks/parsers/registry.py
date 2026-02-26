from __future__ import annotations

from app.webhooks.parsers.base import BaseWebhookParser
from app.webhooks.parsers.github import GitHubParser
from app.webhooks.parsers.gitlab import GitLabParser

PARSERS: dict[str, BaseWebhookParser] = {
    "github": GitHubParser(),
    "gitlab": GitLabParser(),
}


def get_parser(platform: str) -> BaseWebhookParser:
    parser = PARSERS.get(platform)
    if parser is None:
        raise ValueError(f"Unknown platform: {platform}")
    return parser
