"""Converge the two 0026 leaves.

The GitHub App branch and main's Policy->Standard rename each added an 0026
against 0025. A merge migration rather than renumbering: an environment may
already have applied either leaf (the App feature reached staging before it was
reverted off main, and reverting code does not revert a schema), and renaming
one would strand that row and re-run its column adds. Depending on both
converges from any of those states. No operations of its own.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0026_platformconnection_account_login_and_more'),
        ('app', '0026_rename_policy_to_standard'),
    ]

    operations = [
    ]
