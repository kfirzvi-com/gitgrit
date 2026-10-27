# Change management policy

**Owner:** Kfir Zvi · **Approved:** _pending_ · **Next review:** one year after approval · **Applies to:** GitGrit (`kfirzvi-com/gitgrit`) and its deploy configuration (private infrastructure repository)

SOC 2 CC8.1. This policy says how a code change reaches production. The controls
live in GitHub: a ruleset on `main`, a tag ruleset on `v*`, and the `production`
environment in the private infrastructure repository.

## Rules

1. **All changes go through a pull request to `main`.** No direct pushes. The
   `main` ruleset rejects them, and nobody can force-push or delete `main`.
2. **CI must be green before merge.** The `test` and `cli` checks in
   `.github/workflows/ci.yml` are required checks on `main`. A PR with a red
   check cannot be merged.
3. **Staging first.** A merge to `main` deploys to staging automatically.
   A branch can also be deployed to staging by hand for testing.
4. **Production is a tagged release.** A maintainer pushes a `vX.Y.Z` tag on a
   `main` commit. Only maintainers can create `v*` tags; nobody can move or
   delete one.
5. **Every production deploy is approved by someone other than the person who
   tagged it.** The deploy waits in the GitHub `production` environment until
   a required reviewer approves it, and GitHub does not let the tagger approve
   their own deploy. The approver checks that the tag points at `main`, that
   CI passed, and that staging runs the same code. GitHub keeps who approved,
   when, and which version shipped. This record is the change approval.
6. **Verify after every release.** The releaser confirms the version on
   production (`data-git-sha` on the sign-in page matches the tag) and that
   the GitHub release page lists the PRs it contains.
7. **Database migrations** are checked for safety on a live database before
   merge: locks, `NOT NULL` on existing tables, data backfills.
8. **Rollback** follows the rollback runbook in the private infrastructure repository
   (`docs/runbooks/rollback.md`): redeploy the previous tag, revert a
   destructive migration if there is one, verify, and note it in Basecamp.

## Emergency changes

A hotfix for an active incident or a Critical security issue is a normal
release done fast. Nothing is skipped: the fix goes through a PR, CI must be
green, the tag is pushed, and the other maintainer approves the production
deploy. The incident log records the hotfix and its release tag.

## Roles

- **Maintainers:** Kfir Zvi, Tzuf Rosen. They may push `v*` tags and approve
  production deploys.
- **Owner:** reviews this policy once a year and after any change to the
  release flow, and updates the dates in the header.
