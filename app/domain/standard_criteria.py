"""Pure domain rules for standard applicability and health. No I/O, no ORM."""


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
