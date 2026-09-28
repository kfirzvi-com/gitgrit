FROM python:3.13-slim

# LiteLLM powers LLM-based standards (provider abstraction + the agentic loop in
# llm.py). It pulls pydantic. This is the sandbox image's first runtime dep and
# grows it to a few hundred MB — note the impact on the air-gap bundle size.
# Pinned to 1.88.1: 1.89+ lazily imports litellm.proxy -> fastapi during
# completion() with tools, which isn't installed here and would crash standard
# execution. Keep in lockstep with the app's pyproject pin.
#
# PyYAML lets standards parse YAML (the .gitgrit.yml map-file standards). It is
# already installed as a litellm dependency (via huggingface_hub), so pinning it
# here adds nothing to the image or the air-gap bundle — it only stops a litellm
# bump from silently removing it. 6.0.3 is the version litellm 1.88.1 pulls.
RUN pip install --no-cache-dir litellm==1.88.1 pyyaml==6.0.3

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
