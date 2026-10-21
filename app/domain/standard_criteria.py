"""Pure domain rules for standard applicability and health. No I/O, no ORM."""
import logging
import re

logger = logging.getLogger(__name__)

_REF_PREFIX = re.compile(r"^refs/(heads|tags)/")
_REGEX_CHARS = re.compile(r"[*+?()\[\]{}|\\]")


def bare_ref(ref: str | None) -> str:
    """Strip the refs/heads/ or refs/tags/ prefix a webhook ref carries."""
    return _REF_PREFIX.sub("", ref or "")


def literal_ref(pattern: str | None) -> str:
    """Return the branch or tag a Branch/Tag Filter names literally, or ""
    when the filter is empty or a regex. ``main`` and ``^main$`` both name
    ``main``; ``^release/.*`` names nothing, so runs fall back to the default
    branch."""
    name = (pattern or "").strip().removeprefix("^").removesuffix("$")
    if not name or _REGEX_CHARS.search(name):
        return ""
    return name


def applies(
    criteria: dict | None,
    *,
    project_languages,
    event_type: str = "manual",
    ref: str | None = None,
    target_ref: str | None = None,
    skip_event_check: bool = False,
) -> bool:
    """Does a standard with these ``criteria`` apply to an event on a
    project? Its events must include ``event_type`` (unless skipped, as for
    manual runs); its Branch/Tag Filter must match the branch the event is
    *for* — a pull request's ``target_ref``, else ``ref`` (empty matches
    everything, and an event with no ref skips it); and its languages must
    overlap the project's."""
    criteria = criteria or {}
    if not skip_event_check and event_type not in criteria.get("events", []):
        return False
    ref_pattern = criteria.get("ref", "").strip()
    filter_ref = bare_ref(target_ref or ref)
    if ref_pattern and filter_ref:
        try:
            if not re.search(ref_pattern, filter_ref):
                return False
        except re.error:
            logger.warning("Invalid ref regex %r", ref_pattern)
            return False
    return language_matches(criteria.get("languages", []), project_languages or [])


def language_matches(standard_languages: list[str], project_languages: list[str]) -> bool:
    """Return True if a standard applies to a project by language overlap.

    An empty ``standard_languages`` list means the standard is language-agnostic
    and matches every project. Comparison is case-insensitive.
    """
    if not standard_languages:
        return True
    proj = {lang.lower() for lang in project_languages}
    return any(lang.lower() in proj for lang in standard_languages)


def score_to_grade(score: float | None) -> str:
    """Map a 0-100 compliance score to a named grade bucket."""
    if score is None:
        return "unknown"
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "warning"
    return "critical"
