FROM python:3.13-slim

# LiteLLM powers LLM-based standards (provider abstraction + the agentic loop in
# llm.py). It pulls pydantic. This is the sandbox image's first runtime dep and
# grows it to a few hundred MB — note the impact on the air-gap bundle size.
# Pinned to 1.88.1: 1.89+ lazily imports litellm.proxy -> fastapi during
# completion() with tools, which isn't installed here and would crash standard
# execution. Keep in lockstep with the app's pyproject pin.
RUN pip install --no-cache-dir litellm==1.88.1
# PyYAML for standards that read YAML (the "Map file" standards parse
# .gitgrit.yml and docker-compose). litellm only pulls it in by accident
# (via huggingface-hub), so pin it here. Same version the app uses.
RUN pip install --no-cache-dir pyyaml==6.0.3

COPY providers/ /providers/
COPY project_context.py /project_context.py
COPY standard_log.py /standard_log.py
COPY llm.py /llm.py
COPY entrypoint.py /entrypoint.py

# Version stamp baked at build time. Empty for ad-hoc builds; the airgap
# bundle script passes both via --build-arg so operators can prove which
# source tree the bundled sandbox image came from. Symmetric with the
# app image's stamping — both ship together and either could drift.
ARG GIT_SHA=""
ARG GIT_TAG=""
ENV GIT_SHA=$GIT_SHA \
    GIT_TAG=$GIT_TAG

ENTRYPOINT ["python", "/entrypoint.py"]
