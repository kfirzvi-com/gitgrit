FROM python:3.13-slim

COPY providers/ /providers/
COPY project_context.py /project_context.py
COPY entrypoint.py /entrypoint.py

ENTRYPOINT ["python", "/entrypoint.py"]
