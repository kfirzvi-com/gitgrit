from __future__ import annotations

from app.infrastructure.parsers.base import BaseWebhookParser
from app.infrastructure.parsers.github import GitHubParser
from app.infrastructure.parsers.gitlab import GitLabParser

PARSERS: dict[str, BaseWebhookParser] = {
    "github": GitHubParser(),
    "gitlab": GitLabParser(),
}


def get_parser(platform: str) -> BaseWebhookParser:
    parser = PARSERS.get(platform)
    if parser is None:
        raise ValueError(f"Unknown platform: {platform}")
    return parser
