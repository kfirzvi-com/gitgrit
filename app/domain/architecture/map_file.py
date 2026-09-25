"""The repository's own map declaration: a root ``.gitgrit.yml``.

A repository can say what the architecture map should contain instead of
leaving the model to find it out, one tool call at a time::

    components:
      - path: services/orders        # '' or '.' is the repository root
        name: orders
        kind: service                # service | frontend | library | job | infra | other
        description: Order API
        technologies: [Go, gRPC]
        depends_on:                  # other components: a sibling's name/path, org/repo, org/repo#path
          - payments
          - {target: org/auth, label: OAuth}
        infrastructure:
          - {name: PostgreSQL, kind: database, label: orders DB}
        providers: [Stripe]          # third-party services it calls
        consumers: []                # outside systems that call it

Reading it is the first step of every map build
(``RefreshProjectTopology``): ``components`` replace the discovery run, and a
component that has any of ``depends_on`` / ``infrastructure`` / ``providers``
/ ``consumers`` (even an empty list) replaces its dependency run, so a fully
declared repository is mapped without a single model call. Anything left out
is still inferred; without the file the model maps the repository as before.

Only a file-level problem (not YAML, no usable ``components`` list) makes the
whole file unusable. A bad component is dropped and a bad dependency key
leaves that component to the model; each such problem is kept in
``MapFile.warnings``. A file that passes the "Map file" standards parses with
no warnings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    Evidence,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    RepositoryTopology,
    clean_path,
    normalise_components,
    safe_url,
)

MAP_FILE_NAMES = (".gitgrit.yml", ".gitgrit.yaml")
DEPENDENCY_KEYS = ("depends_on", "infrastructure", "providers", "consumers")


class MapFileError(ValueError):
    """The file exists but cannot be used at all; the message says why."""


class _EntryError(ValueError):
    """One part of the file is unusable; the rest still counts."""


@dataclass(frozen=True)
class DeclaredLink:
    name: str
    label: str = ""
    kind: str = "other"  # infrastructure only
    url: str = ""  # providers/consumers only


@dataclass(frozen=True)
class DeclaredComponent:
    decl: ComponentDecl
    has_dependencies: bool = False
    depends_on: tuple[DeclaredLink, ...] = ()
    infrastructure: tuple[DeclaredLink, ...] = ()
    providers: tuple[DeclaredLink, ...] = ()
    consumers: tuple[DeclaredLink, ...] = ()

    def edges(self, source_path: str):
        """``(internal, infrastructure, externals)`` for the component stored
        at ``source_path``."""
        internal = [InternalDependency(source_path, d.name, d.label) for d in self.depends_on]
        infra = [InfrastructureResource(source_path, d.name, d.kind, d.label) for d in self.infrastructure]
        externals = [ExternalLink(source_path, d.name, OUTBOUND, d.url, d.label) for d in self.providers]
        externals += [ExternalLink(source_path, d.name, INBOUND, d.url, d.label) for d in self.consumers]
        return internal, infra, externals


@dataclass(frozen=True)
class MapFile:
    path: str = ""
    components: tuple[DeclaredComponent, ...] = ()
    warnings: tuple[str, ...] = ()

    def matched(self, tree) -> tuple[dict[str, DeclaredComponent], tuple[str, ...]]:
        """Match the declarations to the tree the way ``normalise_components``
        will: ``({stored path: declaration}, dropped paths)``. A declared
        folder with no file under it is dropped, and a lone survivor is keyed
        by the root because the map stores a single component there."""
        dirs: set[str] = set()
        for f in tree:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        found: dict[str, DeclaredComponent] = {}
        dropped = []
        for c in self.components:
            if c.decl.path and c.decl.path not in dirs:
                dropped.append(c.decl.path)
            else:
                found.setdefault(c.decl.path, c)
        if len(found) == 1:
            found = {"": next(iter(found.values()))}
        return found, tuple(dropped)


def _text(value, what: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value).strip()
    raise _EntryError(f"{what} must be a string")


def _links(value, what: str, name_key: str) -> tuple[DeclaredLink, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _EntryError(f"{what} must be a list")
    out = []
    for i, item in enumerate(value):
        if isinstance(item, str):
            item = {name_key: item}
        if not isinstance(item, dict):
            raise _EntryError(f"{what}[{i}] must be a string or a mapping")
        name = _text(item.get(name_key), f"{what}[{i}].{name_key}")
        if not name:
            raise _EntryError(f"{what}[{i}] needs a '{name_key}'")
        url = _text(item.get("url"), f"{what}[{i}].url")
        if url and not safe_url(url):
            raise _EntryError(f"{what}[{i}].url must start with http:// or https://")
        out.append(
            DeclaredLink(
                name=name,
                label=_text(item.get("label"), f"{what}[{i}].label"),
                kind=_text(item.get("kind"), f"{what}[{i}].kind") or "other",
                url=url,
            )
        )
    return tuple(out)


def _component(item, where: str) -> ComponentDecl:
    if not isinstance(item, dict):
        raise _EntryError(f"{where} must be a mapping")
    if "path" not in item:
        raise _EntryError(f"{where} needs a 'path' ('' for the repository root)")
    techs = item.get("technologies") or []
    if not isinstance(techs, list):
        raise _EntryError(f"{where}.technologies must be a list")
    return ComponentDecl(
        path=clean_path(_text(item.get("path"), f"{where}.path")),
        name=_text(item.get("name"), f"{where}.name"),
        kind=_text(item.get("kind"), f"{where}.kind") or "other",
        description=_text(item.get("description"), f"{where}.description"),
        technologies=tuple(_text(t, f"{where}.technologies") for t in techs),
    )


def _dependencies(item, where: str) -> dict:
    return {
        "depends_on": _links(item.get("depends_on"), f"{where}.depends_on", "target"),
        "infrastructure": _links(item.get("infrastructure"), f"{where}.infrastructure", "name"),
        "providers": _links(item.get("providers"), f"{where}.providers", "name"),
        "consumers": _links(item.get("consumers"), f"{where}.consumers", "name"),
    }


def parse_map_file(text: str, path: str = MAP_FILE_NAMES[0]) -> MapFile:
    """Parse ``.gitgrit.yml``. Raises ``MapFileError`` when the file as a
    whole is unusable; a file without a ``components`` key declares nothing."""
    try:
        data = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        raise MapFileError(f"not valid YAML: {str(exc).splitlines()[0]}") from exc
    if data is None:
        return MapFile(path=path)
    if not isinstance(data, dict):
        raise MapFileError("the top level must be a mapping")
    raw = data.get("components")
    if raw is None:
        return MapFile(path=path)
    if not isinstance(raw, list) or not raw:
        raise MapFileError("'components' must be a non-empty list")

    out, warnings = [], []
    for i, item in enumerate(raw):
        where = f"components[{i}]"
        try:
            decl = _component(item, where)
        except _EntryError as exc:
            warnings.append(f"{exc}; component skipped")
            continue
        declared = any(k in item for k in DEPENDENCY_KEYS)
        try:
            deps = _dependencies(item, where)
        except _EntryError as exc:
            warnings.append(f"{exc}; its dependencies are left to the model")
            declared, deps = False, {}
        out.append(DeclaredComponent(decl=decl, has_dependencies=declared, **deps))
    return MapFile(path=path, components=tuple(out), warnings=tuple(warnings))


def declared_topology(map_file: MapFile, tree: list[str], project_name: str) -> RepositoryTopology | None:
    """The whole map from the file alone, or None when any stored component
    still needs a model run (not declared, or its dependencies not declared)."""
    if not map_file.components:
        return None
    found, _dropped = map_file.matched(tree)
    components = normalise_components((c.decl for c in map_file.components), tree, project_name)
    internal, infra, externals = [], [], []
    for component in components:
        declared = found.get(component.path)
        if declared is None or not declared.has_dependencies:
            return None
        i, r, e = declared.edges(component.path)
        internal += i
        infra += r
        externals += e
    return RepositoryTopology(
        components=components,
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infra),
        evidence=Evidence(tree_size=len(tree), map_file=map_file.path, declared=True),
    )
