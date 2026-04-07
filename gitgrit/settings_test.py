import os

os.environ["DEBUG"] = "True"
os.environ.setdefault("SECRET_KEY", "test-insecure-key-not-for-production")

from gitgrit.settings import *  # noqa: F401, F403, E402
