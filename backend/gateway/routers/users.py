# HTTP routes to manage staff accounts (hr_admin only); passwords are never returned or logged
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from gateway.auth.jwt import Principal
from gateway.auth.login import UserError
from gateway.routers.hr_scheduling import require_permission

router = APIRouter(prefix="/api/hr/users", dependencies=[Depends(require_permission("manage_users"))])


class NewUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=40)
    display_name: str = Field(min_length=1, max_length=100)
    role: str = Field(max_length=20)
    password: str = Field(min_length=1, max_length=200)


def _row(user: Any) -> dict[str, str]:
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@router.get("")
def users(request: Request) -> dict[str, Any]:
    return {"users": [_row(user) for user in request.app.state.users.list()]}


@router.post("", status_code=201)
def create(request: Request, body: NewUser, admin: Principal = Depends(require_permission("manage_users"))) -> dict[str, str]:
    try:
        user = request.app.state.users.add(body.username.strip().lower(), body.display_name, body.role, body.password)
    except UserError as error:
        raise HTTPException(409 if str(error) == "user_exists" else 422, str(error)) from None
    request.app.state.audit.record("auth.user_created", user=user.username, role=user.role, by=admin.username)
    return _row(user)


@router.delete("/{username}")
def delete(request: Request, username: str, admin: Principal = Depends(require_permission("manage_users"))) -> dict[str, bool]:
    if username == admin.username:
        raise HTTPException(409, "cannot_delete_self")
    try:
        request.app.state.users.remove(username)
    except UserError as error:
        raise HTTPException(404, str(error)) from None
    request.app.state.audit.record("auth.user_deleted", user=username, by=admin.username)
    return {"ok": True}
