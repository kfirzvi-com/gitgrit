"""What each importance means, in the words the standards table and the API
docs show."""
from app.domain.importance import Importance

DESCRIPTIONS = {
    Importance.REQUIRED: "If it fails, the project fails",
    Importance.MAJOR: "Counts fully toward this project's score",
    Importance.MINOR: "Counts less toward this project's score",
}


def options() -> list[dict]:
    """One entry per importance, most important first, for templates."""
    return [
        {"value": i.value, "label": i.label, "description": DESCRIPTIONS[i]}
        for i in Importance
    ]


def help_text() -> str:
    """One line listing every importance, for API docs."""
    return "; ".join(f"{i.value}: {DESCRIPTIONS[i].lower()}" for i in Importance) + "."
