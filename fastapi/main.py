import os
import warnings
from fastapi_pagination.utils import FastAPIPaginationWarning
from dotenv import load_dotenv

load_dotenv("../.env")
if os.environ.get("SECRET_KEY", None) is None:
    print("can not find env file!")
    exit(-1)

from fastapi import FastAPI

# cloudinary
import cloudinary

# import Database setup
from api.database.setup import engine, get_db
from api.database import models

# import routers
from api.routers import (
    auth,
    user,
    user_pic,
    user_mail,
    user_chat,
    sock,
    sock_pic,
    swipe,
    match,
)

# Setup Cloudinary
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

warnings.simplefilter("ignore", FastAPIPaginationWarning)

# build FastAPI app / Hide schemas from docs
app = FastAPI(
    title="HotSox FastAPI",
    openapi_url=os.environ.get("FASTAPI_URL", "/fastapi/v1") + "/openapi.json",
    docs_url=os.environ.get("FASTAPI_URL", "/fastapi/v1") + "/docs",
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)


# API Limiter
from slowapi.errors import RateLimitExceeded
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# setup SQLAlchemy database engine
# models.Base.metadata.create_all(engine)

# include API routs
# authentication (JWT token)
app.include_router(auth.router)
# user endpoints
app.include_router(user.router)
app.include_router(user_pic.router)
app.include_router(user_mail.router)
app.include_router(user_chat.router)
# sock endpoints
app.include_router(sock.router)
app.include_router(sock_pic.router)
# swipe endpoints
app.include_router(swipe.router)
# match endpoints
app.include_router(match.router)
