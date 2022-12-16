from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from ..dependencies import (
    API_KEY_NAME,
    API_KEY_SCOPE,
    Token,
    User,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_odoo_env,
    odoo_env,
)
from ..settings import SETTINGS

router = APIRouter(
    tags=["auth"],
    dependencies=[Depends(odoo_env)],
    responses={404: {"description": "Not found"}},
)


def create_odoo_api_key_for_service_users(username):
    """
    Creates Odoo API KEY only when user is a member of a group
    """
    with get_odoo_env() as env:
        user = env["res.users"].search([("login", "=", username)])
        # Only allow creation of token for users in the group
        if not user.with_user(user).user_has_groups(
            "order_dispatch.dispatch_group_api_driver_user"
        ):
            return False
        scope = API_KEY_SCOPE
        name = API_KEY_NAME
        # Follows `odoo.addons.base.models.res_users.APIKeys._generate`
        env["res.users.apikeys"].search(
            [
                ("name", "=", name),
                ("user_id.id", "=", user.id),
            ]
        ).unlink()
        r = env["res.users.apikeys"].with_user(user)._generate(scope=scope, name=name)
        # k = env['res.users.apikeys'].search([])
        return r


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    # Authenticate user with Odoo
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Check to see if user API Key is present for the user
    # Present, so wrap this to JWT
    # Not present (not in the group), return 401 - cannot authenticate. Please contact admin.
    __api_key__ = create_odoo_api_key_for_service_users(user.username)
    if not __api_key__:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cannot authenticate user. Please contact administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # default 4 hours
    access_token_expires = timedelta(
        minutes=int(SETTINGS.get("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 4)))
    )
    access_token = create_access_token(
        data={"sub": f"{user.username}|{__api_key__}", "scopes": form_data.scopes},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


# TODO: Comment/remove after test
@router.get("/users/me/", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user


# # TODO: Comment/remove after test
# @router.get("/users/me/items/")
# async def read_own_items(current_user: User = Depends(get_current_active_user)):
#     return [{"item_id": "Foo", "owner": current_user.username}]
