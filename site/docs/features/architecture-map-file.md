# Architecture Map File

GitGrit draws an architecture map of every repository: its components (services, apps, libraries, jobs, infrastructure) and what each one depends on. By default an LLM builds the map by exploring the repository file by file, which can take dozens of model calls.

A `.gitgrit.yml` file at the repository root lets the repository describe its own map instead.

## How GitGrit uses it

Every map build starts by looking for `.gitgrit.yml`:

1. **No file:** the LLM maps the repository as usual.
2. **Components listed:** GitGrit skips the LLM's discovery step and uses your list.
3. **A component lists its dependencies:** GitGrit skips the LLM run for that component. An empty list (`depends_on: []`) counts.
4. **Every component lists its dependencies:** the map is built from the file alone, with no LLM call.

Anything the file leaves out is still filled in by the LLM. This makes maps fast and reliable even on free or rate-limited models.

## Format

```yaml
components:
  - path: services/orders        # folder in the repository; '' is the repository root
    name: orders
    kind: service                # service | frontend | library | job | infra | other
    description: Order API
    technologies: [Go, gRPC]
    depends_on:                  # other components
      - payments                 # a component in this repository, by name or path
      - {target: my-org/auth, label: OAuth}   # another repository (my-org/repo or my-org/repo#path)
    infrastructure:              # datastores, caches, queues, buckets it owns
      - {name: PostgreSQL, kind: database, label: orders DB}   # kind: database | cache | queue | storage | other
    providers:                   # third-party services it calls
      - {name: Stripe, url: https://stripe.com}
    consumers: []                # outside systems that call it

ignore:                          # folders that are not components (used by the standards)
  - sandbox
```

A single-app repository needs one component:

```yaml
components:
  - path: ''
    depends_on: []
    providers: [Stripe]
```

Rules:

- `url` must start with `http://` or `https://`.
- If a component's entry is broken, only that component is skipped (or left to the LLM). If the whole file is broken (not valid YAML, no `components` list), GitGrit ignores it and the LLM maps the repository.
- A declared folder with no files in it is left out of the map.

## Keep it correct

The **Architecture Map Ready** pack in the [marketplace](marketplace.md) checks the file on every push:

| Standard | Checks |
|----------|--------|
| Map file: components are declared in .gitgrit.yml | The file exists and every entry is valid. If it is missing, the message prints a starting file to commit. |
| Map file: every deployable folder is declared | Every folder with a Dockerfile, Terraform or a package manifest is a component, inside one, or under `ignore`. |
| Map file: every component declares its dependencies | Every component lists its dependencies, targets name real components, and `docker-compose` `depends_on` links are in the file. |

A repository that passes all three is mapped with no LLM calls.
