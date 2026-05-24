FROM python:3.13-slim

COPY providers/ /providers/
COPY project_context.py /project_context.py
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
