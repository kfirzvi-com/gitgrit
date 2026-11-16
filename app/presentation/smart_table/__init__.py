"""A smart table: a list on a page its reader sorts and groups in place,
alongside the filter search (``app.presentation.filter_search``) that
filters the same rows.

- ``SortOption``: one order the rows can take (``score``, numbers or text).
- ``GroupOption``: one way to group the rows (``owner``), the order and
  labels of its groups when they are known up front.
- ``SmartTable``: the sorts and groupings one list offers and its default
  ones; ``as_dict()`` is the config the page's script reads
  (``app/static/app/smart_table/``).
- ``ProjectRow`` / ``StackRow``: a project or a stack as its row shows it.
- ``ProjectListSmartTable`` / ``StackListSmartTable``: the Projects and
  Stacks pages' tables.

Each row says what it sorts by in ``data-sort-<key>`` and the groups it
falls in in ``data-group-<key>`` (``|`` between several: a project in two
stacks shows under both).
"""
from app.presentation.smart_table.group_option import GroupOption
from app.presentation.smart_table.project_list_smart_table import ProjectListSmartTable
from app.presentation.smart_table.project_row import ProjectRow
from app.presentation.smart_table.smart_table import SmartTable
from app.presentation.smart_table.sort_option import SortOption
from app.presentation.smart_table.stack_list_smart_table import StackListSmartTable
from app.presentation.smart_table.stack_row import StackRow

__all__ = [
    "GroupOption",
    "ProjectListSmartTable",
    "ProjectRow",
    "SmartTable",
    "SortOption",
    "StackListSmartTable",
    "StackRow",
]
