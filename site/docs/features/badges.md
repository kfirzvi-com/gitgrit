# Compliance Badges

Embed a live badge in your repository README to show your project's GitGrit [grade](grades.md).

## How it works

Each project has a public badge endpoint that returns an SVG image:

```
https://app.gitgrit.dev/badge/<project-id>.svg
```

The badge shows your project's grade letter, color-coded:

- **Green** — A+, A or B
- **Orange** — C or D
- **Red** — F (a critical standard is failing or could not be verified)
- **Gray** — no grade yet

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

Badges are cached for 5 minutes. After a standard run changes the grade, the badge will reflect the new letter within 5 minutes.
