import os

from auth0.authentication import GetToken
from fastapi import FastAPI

app = FastAPI()
SELF_URL = os.environ["AUTH_SERVICE_URL"]
token_client = GetToken(os.environ["AUTH0_DOMAIN"], os.environ["AUTH0_CLIENT_ID"])
