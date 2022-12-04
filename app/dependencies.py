# References:
# - https://github.com/acsone/odooxp2021-fastapi/blob/master/odoo_fastapi_demo/deps.py
# - https://fastapi.tiangolo.com/tutorial/bigger-applications/
# - https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
import contextlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import odoo
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from jose import JWTError, jwt
from odoo.api import Environment
from passlib.context import CryptContext
from pydantic import BaseModel

from .settings import SETTINGS


def odoo_env() -> Environment:
    #
    # /!\ With Odoo < 15 you need to wrap all this in 'with
    #     Environment.manage()' and apply this Odoo patch:
    #     https://github.com/odoo/odoo/pull/70398, to properly handle context
    #     locals in an async program.
    #
    # check_signaling() is to refresh the registry and cache when needed.
    # HACK: when running API outside of docker network where Odoo is running
    if odoo.tools.config["db_host"] == "host.docker.internal":
        odoo.tools.config["db_host"] = "0.0.0.0"
        if "DEV_ADDONS_PATH" in os.environ:
            odoo.tools.config["addons_path"] += "," + os.environ["DEV_ADDONS_PATH"]
    registry = odoo.registry(odoo.tools.config["db_name"]).check_signaling()
    # manage_change() is to signal other instances when the registry or cache
    # needs refreshing.
    with registry.manage_changes():
        # The cursor context manager commits unless there is an exception.
        with registry.cursor() as cr:
            try:
                ctx = Environment(cr, odoo.SUPERUSER_ID, {})["res.users"].context_get()
            except Exception as e:
                ctx = {"lang": "en_US"}
            yield Environment(cr, odoo.SUPERUSER_ID, ctx)


# AUTHENTICATION
# to get a string like this run:
# openssl rand -hex 32
load_dotenv(Path("../.env"))
ALGORITHM = "HS256"

#
# fake_users_db = {
#     "johndoe": {
#         "username": "johndoe",
#         "full_name": "John Doe",
#         "email": "johndoe@example.com",
#         "hashed_password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
#         "disabled": False,
#     }
# }


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None
    scopes: List[str] = []


class User(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None


class UserInDB(User):
    hashed_password: str


class ImproperlyConfigured(Exception):
    pass


pwd_context = CryptContext(schemes=["bcrypt", "sha256_crypt"], deprecated="auto")
try:
    SECRET_KEY = SETTINGS["SECRET_KEY"]
except KeyError:
    raise ImproperlyConfigured("SECRET_KEY not set.")
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="token",
    scopes={
        "me_profile": "Read information about the current user",
        "orders:list": "List orders",
    },
)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def odoo_verify_password(user, plain_password):
    with get_odoo_env() as env:
        user = env["res.users"].browse([user.id])
        user = user.with_user(user)
        try:
            user._check_credentials(plain_password, {"interactive": False})
        except odoo.exceptions.AccessDenied:
            return
        return True


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user(db, username: str):
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)


@contextlib.contextmanager
def get_odoo_env():
    yield from odoo_env()


def get_odoo_user(username: str):
    with get_odoo_env() as env:
        user = env["res.users"].search(
            [("login", "=", username)]
        )  # Odoo ref to 'login' instead of username
        if len(user) != 1:
            return
        return (
            UserInDB(
                username=user.login,
                email=user.email,
                full_name=user.name,
                disabled=not user.active,
                hashed_password="",
            ),
            user,
        )


# def authenticate_user(fake_db, username: str, password: str):
def authenticate_user(username: str, password: str):
    # user = get_user(fake_db, username)
    user, odoo_user = get_odoo_user(username)
    if not user:
        return False
    # if not verify_password(password, user.hashed_password):
    if not odoo_verify_password(odoo_user, password):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    security_scopes: SecurityScopes,
    token: str = Depends(oauth2_scheme),
):
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = "Bearer"
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_scopes = payload.get("scopes", [])
        token_data = TokenData(scopes=token_scopes, username=username)
    except JWTError:
        raise credentials_exception
    # user = get_user(fake_users_db, username=token_data.username)
    user, __ = get_odoo_user(username=token_data.username)
    if user is None:
        raise credentials_exception
    for scope in security_scopes.scopes:
        if scope not in token_data.scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )
    return user


async def get_current_active_user(
    current_user: User = Security(get_current_user, scopes=["me_profile"]),
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
