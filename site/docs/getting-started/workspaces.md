# Workspaces & Members

A workspace holds everything your team shares: platform connections, projects, stacks, standards and AI providers. Each person belongs to one or more workspaces, with a role in each.

Workspaces are created by the GitGrit team (on a self-hosted install, by a [superuser](../self-hosting/operations.md#managing-access)), usually when they approve the first person from your company. That person becomes its owner.

## Roles

| | Owner | Admin | Member |
|---|:-:|:-:|:-:|
| Use projects, stacks and standards | ✓ | ✓ | ✓ |
| Manage connections, AI providers and API tokens | ✓ | ✓ | |
| Invite and remove members and admins | ✓ | ✓ | |
| Make someone an owner, change or remove an owner | ✓ | | |
| Delete the workspace | ✓ | | |

A workspace always has at least one owner. Its last owner can't step down, be removed or leave; make someone else an owner first.

## Managing members

Everything is under **Workspace Settings → Members & Permissions**:

- **Invite** someone by the email they signed in with. They need a GitGrit account already (approved, on the hosted service).
- **Change a role** from the dropdown in their row. GitGrit asks you to confirm and explains what the new role can do.
- **Remove** someone, or **Leave** the workspace yourself.

Each row shows who gave the person their current role, and when.

## Deleting a workspace

Owners find it under **Workspace Settings → Danger Zone**. To confirm, you type the workspace's name exactly. Deleting is permanent: every project, standard, run, connection and member goes with it, and GitGrit removes the webhooks it added to your repositories. A GitHub App installation stays on your GitHub organisation; uninstall it there if you no longer want it.
