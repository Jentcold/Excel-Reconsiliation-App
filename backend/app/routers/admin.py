from __future__ import annotations

from appwrite.exception import AppwriteException
from appwrite.id import ID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from ..appwrite_client import as_dict, users
from ..auth import CurrentUser, require_admin, role_of
from ..schema import ROLES

router = APIRouter(prefix="/admin", tags=["admin"])

MIN_PASSWORD = 8


class NewAccount(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)
    role: str


class RoleChange(BaseModel):
    role: str


class PasswordReset(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)


def _serialise(account) -> dict:
    account = as_dict(account)
    return {
        "id": account["$id"],
        "email": account.get("email"),
        "name": account.get("name"),
        "role": role_of(account.get("labels")),
        "status": account.get("status"),
        "created_at": account.get("$createdAt"),
    }


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Role must be one of: {', '.join(ROLES)}.")
    return role


@router.get("/users")
async def list_users(admin: CurrentUser = Depends(require_admin)):
    result = users.list()
    listed = result.get("users", []) if isinstance(result, dict) else getattr(result, "users", [])
    return {"users": [_serialise(u) for u in listed]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_account(body: NewAccount, admin: CurrentUser = Depends(require_admin)):
    _check_role(body.role)
    try:
        account = users.create(ID.unique(), body.email, None, body.password, body.name)
    except AppwriteException as e:
        if "already exists" in str(e).lower():
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"An account already exists for {body.email}.")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    account = users.update_labels(as_dict(account)["$id"], [body.role])
    return {"user": _serialise(account),
            "message": f"Created {body.email} as {body.role}."}


@router.patch("/users/{user_id}/role")
async def change_role(user_id: str, body: RoleChange,
                      admin: CurrentUser = Depends(require_admin)):
    _check_role(body.role)
    if user_id == admin.id and body.role != "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "You can't remove your own admin role.")
    try:
        account = users.update_labels(user_id, [body.role])
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")
    return {"user": _serialise(account), "message": f"Role set to {body.role}."}


@router.patch("/users/{user_id}/password")
async def reset_password(user_id: str, body: PasswordReset,
                         admin: CurrentUser = Depends(require_admin)):
    try:
        users.update_password(user_id, body.password)
    except AppwriteException as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"message": "Password updated. Share it with the account holder directly."}


@router.patch("/users/{user_id}/status")
async def set_status(user_id: str, enabled: bool,
                     admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id and not enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't disable your own account.")
    try:
        account = users.update_status(user_id, enabled)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")
    return {"user": _serialise(account),
            "message": f"Account {'enabled' if enabled else 'disabled'}."}


@router.delete("/users/{user_id}")
async def delete_account(user_id: str, admin: CurrentUser = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't delete your own account.")
    try:
        users.delete(user_id)
    except AppwriteException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")
    return {"message": "Account deleted."}
