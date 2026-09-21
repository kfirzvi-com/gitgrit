"""The architecture domain: what a repository is made of and how the pieces
depend on each other.

Pure Python (no Django, no network, no model calls). The persistence models
live in ``app.domain.models``; this package holds the *rules* that turn an
inferred picture of a repository into stable components and edges, so those
rules can be tested without a database or an LLM.

* ``topology``  — value objects for an inferred repository topology, path
                  normalisation, and the evidence gate.
* ``resolve``   — mapping model-returned names onto the workspace roster and
                  correcting common misclassifications.
* ``reconcile`` — deciding which components to keep, create and remove on a
                  re-run, and how stack memberships carry over.
* ``naming``    — canonical names for external services.
"""
