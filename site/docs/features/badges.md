# Compliance Badges

Embed a live compliance badge in your repository README to show your GitGrit compliance score.

## How it works

Each project has a public badge endpoint that returns an SVG image:

```
https://app.gitgrit.dev/badge/<project-id>.svg
```

The badge shows your project's compliance score, color-coded:

- **Green** — score >= 80%
- **Orange** — score >= 50%
- **Red** — score < 50%
- **Gray** — no data yet

## Adding a badge

1. Go to your project detail page in GitGrit
2. Find the **Badge** card in the sidebar
3. Copy the Markdown or HTML snippet
4. Paste it in your repository's README

### Markdown

```markdown
[![gitgrit](https://app.gitgrit.dev/badge/<project-id>.svg)](https://app.gitgrit.dev/projects/<project-id>/)
```

### HTML

```html
<a href="https://app.gitgrit.dev/projects/<project-id>/">
  <img src="https://app.gitgrit.dev/badge/<project-id>.svg" alt="gitgrit">
</a>
```

## Caching

Badges are cached for 5 minutes. After a policy evaluation updates the score, the badge will reflect the new score within 5 minutes.
