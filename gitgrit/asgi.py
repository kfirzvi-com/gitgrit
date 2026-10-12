"""
ASGI config for gitgrit project.

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gitgrit.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()
