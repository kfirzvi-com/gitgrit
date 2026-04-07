# GitGrit Docs Site

Landing page and documentation for [gitgrit.dev](https://gitgrit.dev), built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/).

## Setup

```sh
uv sync --project site
```

## Development

```sh
uv run --project site mkdocs serve -f site/mkdocs.yml
```

Open http://127.0.0.1:8000

## Build

```sh
uv run --project site mkdocs build -f site/mkdocs.yml -d build
```

Output is written to `site/build/`.
