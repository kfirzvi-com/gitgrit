"""The filter search in templates (``app.presentation.filter_search``).

    {% load filter_search_tags %}
    {% standard_picker_filter_search workspace_standards as filter_search %}
    {% filter_search filter_search label="Filter standards" %}
    <tr data-filter-row data-filter-label="{{ standard|standard_label_values }}">

``filter_search`` renders the search box, its suggestion list and a menu
button per choice field; the rows it filters are the ``data-filter-row``
elements inside the nearest ``data-filter-scope``.
"""
import uuid

from django import template

from app.presentation.filter_search import StandardListFilterSearch, StandardPickerFilterSearch

register = template.Library()

# Between several values in one data-filter-<key> attribute.
VALUE_SEPARATOR = "|"


@register.simple_tag
def standard_picker_filter_search(standards):
    return StandardPickerFilterSearch.for_standards(standards)


@register.simple_tag
def standard_list_filter_search(standards):
    return StandardListFilterSearch.for_standards(standards)


@register.inclusion_tag("partials/filter_search.html")
def filter_search(search, label="Filter"):
    """The search box for ``search`` (a ``FilterSearch``); ``label`` names it
    for screen readers."""
    return {
        "search": search,
        "config": search.as_dict(),
        "label": label,
        "uid": uuid.uuid4().hex[:8],
    }


@register.filter
def standard_label_values(standard):
    """A standard's labels as ``label:`` matches them: ``"ci|security"``."""
    return VALUE_SEPARATOR.join(label.name.lower() for label in standard.labels.all())


@register.filter
def standard_status_values(standard):
    """What ``is:`` matches on the Standards page: ``"enabled|draft"``."""
    return VALUE_SEPARATOR.join(StandardListFilterSearch.statuses_of(standard))
