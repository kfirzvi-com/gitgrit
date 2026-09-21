"""Adapters for the architecture ports (``app.application.architecture.ports``).

* ``snapshots``     — ``PlatformSnapshot`` (GitHub/GitLab API) and
                      ``LocalDirSnapshot`` (a checkout on disk).
* ``toolbox``       — the read-only repository tools handed to a model.
* ``llm_inference`` — two-phase LLM inference: discover components, then map
                      each component's dependencies.
* ``fake``          — fixture-driven inference for tests and offline dev.
"""
