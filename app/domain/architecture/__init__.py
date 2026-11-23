"""The architecture domain: how a workspace's projects depend on each other
and on the outside world.

Pure Python (no Django, no network, no model calls). The persistence models
live in ``app.domain.models``; this package holds the *rules* that turn an
inferred picture of a project into edges, so those rules can be tested
without a database or an LLM.

* ``topology``  — value objects for an inferred project topology, path
                  normalisation, and the evidence gate.
* ``resolve``   — mapping model-returned names onto the workspace roster and
                  correcting common misclassifications.
* ``naming``    — canonical names for external services.
"""
