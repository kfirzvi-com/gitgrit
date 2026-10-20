"""Pure domain rules for standard applicability. No I/O, no ORM."""


def language_matches(standard_languages: list[str], project_languages: list[str]) -> bool:
    """Return True if a standard applies to a project by language overlap.

    An empty ``standard_languages`` list means the standard is language-agnostic
    and matches every project. Comparison is case-insensitive.
    """
    if not standard_languages:
        return True
    proj = {lang.lower() for lang in project_languages}
    return any(lang.lower() in proj for lang in standard_languages)

