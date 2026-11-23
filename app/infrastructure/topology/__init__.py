"""Adapters for the architecture ports (``app.application.architecture.ports``).

* ``snapshots``     — ``PlatformSnapshot`` (GitHub/GitLab API) and
                      ``LocalDirSnapshot`` (a checkout on disk).
* ``toolbox``       — the read-only repository tools handed to a model.
* ``llm_inference`` — LLM inference: map one project's dependencies, and for a
                      whole-repository project discover the apps and services
                      inside it (suggested projects).
* ``fake``          — fixture-driven inference for tests and offline dev.
"""
