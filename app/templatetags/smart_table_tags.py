"""Smart tables in templates (``app.presentation.smart_table``): a list its
reader sorts and groups in place, next to the filter search that filters it.

    {% load smart_table_tags %}
    {% project_list_smart_table as table %}
    <div data-smart-table>
      {% smart_table_toolbar table %}
      <table> <th data-smart-sort="score">Score</th> …
        <tbody data-smart-table-body>
          <tr data-filter-row data-smart-row data-sort-score="82" data-group-owner="Platform"> …

``smart_table_toolbar`` renders the config the script reads, the row count
and the Group and Sort menus; a ``data-smart-sort`` header sorts by its key
when clicked.
"""
import uuid

from django import template

from app.presentation.smart_table import (
    MarketplaceSmartTable,
    ProjectListSmartTable,
    StackListSmartTable,
    StandardListSmartTable,
)

register = template.Library()


@register.simple_tag
def project_list_smart_table():
    return ProjectListSmartTable.build()


@register.simple_tag
def stack_list_smart_table():
    return StackListSmartTable.build()


@register.simple_tag
def marketplace_smart_table():
    return MarketplaceSmartTable.build()


@register.simple_tag
def standard_list_smart_table():
    return StandardListSmartTable.build()


@register.inclusion_tag("partials/smart_table_toolbar.html")
def smart_table_toolbar(table):
    """The toolbar for ``table`` (a ``SmartTable``)."""
    return {"table": table, "config": table.as_dict(), "uid": uuid.uuid4().hex[:8]}
