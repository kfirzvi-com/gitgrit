"""Changing many projects or standards at once, from the Projects and
Standards pages' bulk bars. Each change goes through the same use case as
changing one (``project_management``, ``stack_service``,
``StandardService``), so its events and runs follow as they would for one;
an item the change cannot apply to is skipped and said why.

- ``BulkEditResult``: how many changed, stayed as they were or were skipped.
- ``StandardBulkEdit``: enable, disable, label, unlabel, delete.
- ``ProjectBulkEdit``: owner, lifecycle, stack, attach or detach a standard.
- ``MarketplaceBulkInstall``: install or update Marketplace standards.
"""
from app.application.bulk_edit.bulk_edit_result import BulkEditResult
from app.application.bulk_edit.marketplace_bulk_install import MarketplaceBulkInstall
from app.application.bulk_edit.project_bulk_edit import ProjectBulkEdit
from app.application.bulk_edit.standard_bulk_edit import StandardBulkEdit

__all__ = ["BulkEditResult", "MarketplaceBulkInstall", "ProjectBulkEdit", "StandardBulkEdit"]
