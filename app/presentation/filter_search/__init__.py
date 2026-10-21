"""A GitHub-like filter search for a list on a page: free words plus
qualifiers (``is:attached``, ``label:ci,security``, ``-importance:minor``),
with autocomplete for fields and values and a menu button per choice field.

- ``FilterValue``: one value a field can take (``"required"`` shown as
  "Required").
- ``FilterField``: one field the query can name (``label:``), its values
  and whether free words search it.
- ``FilterSearch``: the fields one list offers; ``as_dict()`` is the config
  the page's script reads (``app/static/app/filter_search/``).
- ``StandardPickerFilterSearch`` / ``StandardListFilterSearch``: the fields
  for a project's standards picker and for the workspace's Standards page.

Each filtered row says its own values in ``data-filter-<key>`` attributes
(``|`` between several), so the search filters any list the same way.
"""
from app.presentation.filter_search.filter_field import FilterField
from app.presentation.filter_search.filter_search import FilterSearch
from app.presentation.filter_search.filter_value import FilterValue
from app.presentation.filter_search.standard_list_filter_search import StandardListFilterSearch
from app.presentation.filter_search.standard_picker_filter_search import StandardPickerFilterSearch

__all__ = [
    "FilterField",
    "FilterSearch",
    "FilterValue",
    "StandardListFilterSearch",
    "StandardPickerFilterSearch",
]
