---
description: Report the current GitGrit compliance grade and top offending policies for the resolved project.
---

Read the GitGrit session state file to get the resolved `project_id`. Use the Bash tool:

```bash
cat "${XDG_CACHE_HOME:-$HOME/.cache}/gitgrit/$(git rev-parse --absolute-git-dir | sha256sum | cut -c1-16).json" 2>/dev/null
```

If the command prints nothing, tell the developer GitGrit is not active for this session and stop.

Otherwise call `gitgrit/get_project_status(project_id=<id>)` and report the grade and top 1–2 offenders in a single sentence.
