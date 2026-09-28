"""The ``.gitgrit.yml`` map file: a repository's topology, written by hand.

A developer commits ``.gitgrit.yml`` at the repository root to describe its
components and their dependencies. It holds exactly what the two LLM phases
return (component discovery, then each component's dependencies), so a valid
file replaces the model run and everything after it stays the same.

``parse_map_file`` turns the file into a ``RepositoryTopology`` or raises
``InvalidMapFile`` with the first rule it breaks; ``dump_map_file`` writes a
topology back in the same format (used to store the LLM result). Pure: no
Django, no I/O.
"""
from __future__ import annotations

import re
from typing import Iterable

import yaml

from app.domain.architecture.topology import (
    COMPONENT_KINDS,
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    MAX_COMPONENTS,
    RepositoryTopology,
    clean_path,
)

MAP_FILE = ".gitgrit.yml"
VERSION = 1
MAP_INFRA_KINDS = ("database", "cache", "queue", "storage")
DEPENDENCY_KEYS = ("internal", "infrastructure", "external_providers", "external_consumers")

# ``owner/repo`` (GitLab may nest groups), optionally ``#sub/dir``; or ``#sub/dir``
# for a sibling component of this repository.
_TARGET = re.compile(r"^(?:[^\s#/]+(?:/[^\s#/]+)+(?:#[^\s#]+)?|#[^\s#]+)$")


class InvalidMapFile(ValueError):
    """The map file breaks one of the format rules; the message says which."""


def _dirs(tree: Iterable[str]) -> set[str]:
    dirs: set[str] = set()
    for f in tree:
        parts = f.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return dirs


def _text(entry: dict, key: str, where: str, *, required: bool = False) -> str:
    value = entry.get(key)
    if value is None:
        if required:
            raise InvalidMapFile(f"{where}: '{key}' is required")
        return ""
    if not isinstance(value, str):
        raise InvalidMapFile(f"{where}: '{key}' must be a string")
    return value


def _entries(deps: dict, key: str, where: str) -> list[dict]:
    value = deps.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidMapFile(f"{where}.{key} must be a list")
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise InvalidMapFile(f"{where}.{key}[{i}] must be a mapping")
    return value


def parse_map_file(text: str, tree: Iterable[str]) -> RepositoryTopology:
    """Parse and validate a map file against the repository's file list.

    Component paths are cleaned the way model paths are (``./apps/api/`` →
    ``apps/api``) and must name an existing directory; dependencies are keyed
    by those cleaned paths. Names, kinds and technologies are returned as
    written — the caller normalises them like an LLM answer.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InvalidMapFile(f"not valid YAML ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise InvalidMapFile("the top level must be a mapping")
    if data.get("version") != VERSION:
        raise InvalidMapFile(f"'version' must be {VERSION}")
    raw_components = data.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise InvalidMapFile("'components' must be a non-empty list")
    if len(raw_components) > MAX_COMPONENTS:
        raise InvalidMapFile(f"at most {MAX_COMPONENTS} components are allowed")

    dirs = _dirs(tree)
    components: list[ComponentDecl] = []
    internal: list[InternalDependency] = []
    externals: list[ExternalLink] = []
    infra: list[InfrastructureResource] = []
    seen: set[str] = set()
    for i, c in enumerate(raw_components):
        where = f"components[{i}]"
        if not isinstance(c, dict):
            raise InvalidMapFile(f"{where} must be a mapping")
        path = clean_path(_text(c, "path", where, required=True))
        if path and path not in dirs:
            raise InvalidMapFile(f"{where}: path '{path}' is not a directory in the repository")
        if path in seen:
            raise InvalidMapFile(f"{where}: duplicate path '{path}'")
        seen.add(path)

        kind = c.get("kind", "other")
        if kind not in COMPONENT_KINDS:
            raise InvalidMapFile(f"{where}: kind must be one of {', '.join(COMPONENT_KINDS)}")
        technologies = c.get("technologies") or []
        if not isinstance(technologies, list) or not all(isinstance(t, str) for t in technologies):
            raise InvalidMapFile(f"{where}: 'technologies' must be a list of strings")
        components.append(
            ComponentDecl(
                path=path,
                name=_text(c, "name", where),
                kind=kind,
                description=_text(c, "description", where),
                technologies=tuple(technologies),
            )
        )

        deps = c.get("dependencies") or {}
        where = f"{where}.dependencies"
        if not isinstance(deps, dict):
            raise InvalidMapFile(f"{where} must be a mapping")
        unknown = sorted(str(k) for k in deps if k not in DEPENDENCY_KEYS)
        if unknown:
            raise InvalidMapFile(f"{where}: unknown key(s) {', '.join(unknown)}")

        for j, d in enumerate(_entries(deps, "internal", where)):
            at = f"{where}.internal[{j}]"
            target = _text(d, "target", at, required=True).strip()
            if not _TARGET.match(target):
                raise InvalidMapFile(
                    f"{at}: target '{target}' must be owner/repo, owner/repo#sub/dir or #sub/dir"
                )
            internal.append(InternalDependency(path, target, _text(d, "label", at)))
        for j, d in enumerate(_entries(deps, "infrastructure", where)):
            at = f"{where}.infrastructure[{j}]"
            kind = d.get("kind")
            if kind is not None and kind not in MAP_INFRA_KINDS:
                raise InvalidMapFile(f"{at}: kind must be one of {', '.join(MAP_INFRA_KINDS)}")
            infra.append(
                InfrastructureResource(
                    path, _text(d, "name", at, required=True), kind or "other", _text(d, "label", at)
                )
            )
        for key, direction in (("external_providers", OUTBOUND), ("external_consumers", INBOUND)):
            for j, d in enumerate(_entries(deps, key, where)):
                at = f"{where}.{key}[{j}]"
                externals.append(
                    ExternalLink(
                        path,
                        _text(d, "name", at, required=True),
                        direction,
                        _text(d, "url", at),
                        _text(d, "label", at),
                    )
                )

    return RepositoryTopology(
        components=tuple(components),
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infra),
    )


def _with(entry: dict, **optional) -> dict:
    """``entry`` plus the optional fields that are set (keeps the file short)."""
    return {**entry, **{k: v for k, v in optional.items() if v}}


def dump_map_file(topology: RepositoryTopology) -> str:
    """Write a topology as ``.gitgrit.yml`` text, in the format ``parse_map_file`` reads."""
    components = []
    for c in topology.components:
        deps = {
            "internal": [
                _with({"target": d.target_ref}, label=d.label)
                for d in topology.internal
                if d.source_path == c.path
            ],
            "infrastructure": [
                # "other" is the default; any kind outside the file's set is left out.
                _with({"name": i.name}, kind=i.kind if i.kind in MAP_INFRA_KINDS else "", label=i.label)
                for i in topology.infrastructure
                if i.source_path == c.path
            ],
            "external_providers": [
                _with({"name": e.name}, url=e.url, label=e.label)
                for e in topology.externals
                if e.source_path == c.path and e.direction != INBOUND
            ],
            "external_consumers": [
                _with({"name": e.name}, url=e.url, label=e.label)
                for e in topology.externals
                if e.source_path == c.path and e.direction == INBOUND
            ],
        }
        components.append(
            _with(
                {"path": c.path, "name": c.name, "kind": c.kind},
                description=c.description,
                technologies=list(c.technologies),
                dependencies={k: v for k, v in deps.items() if v},
            )
        )
    return yaml.safe_dump(
        {"version": VERSION, "components": components},
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
