from __future__ import annotations

import time
from dataclasses import dataclass

from appwrite.exception import AppwriteException
from appwrite.services.account import Account
from fastapi import Depends, HTTPException, Request, status

from .appwrite_client import admin_client, as_dict, session_client, users
from .config import settings
from .schema import ROLE_ADMIN, ROLE_COMMERCIAL, ROLE_SALES, ROLES


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def role_of(labels: list[str] | None) -> str:
    for label in labels or []:
        if label in ROLES:
            return label
    return ROLE_SALES


def create_session(email: str, password: str) -> tuple[str, CurrentUser]:
    try:
        session = as_dict(Account(admin_client()).create_email_password_session(email, password))
    except AppwriteException:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    account = as_dict(users.get(session["userId"]))
    user = CurrentUser(
        id=account["$id"],
        email=account.get("email", ""),
        name=account.get("name") or account.get("email", ""),
        role=role_of(account.get("labels")),
    )
    return session["secret"], user


def destroy_session(secret: str) -> None:
    _verified.pop(secret, None)
    try:
        Account(session_client(secret)).delete_session("current")
    except AppwriteException:
        pass


_VERIFY_TTL = 30.0
_verified: dict[str, tuple[float, CurrentUser]] = {}


def _remember(secret: str, user: CurrentUser) -> None:
    now = time.monotonic()
    if len(_verified) > 64:
        for key, (expires, _) in list(_verified.items()):
            if expires <= now:
                del _verified[key]
    _verified[secret] = (now + _VERIFY_TTL, user)


async def current_user(request: Request) -> CurrentUser:
    secret = request.cookies.get(settings.session_cookie)
    if not secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    cached = _verified.get(secret)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        account = as_dict(Account(session_client(secret)).get())
    except AppwriteException:
        _verified.pop(secret, None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = CurrentUser(
        id=account["$id"],
        email=account.get("email", ""),
        name=account.get("name") or account.get("email", ""),
        role=role_of(account.get("labels")),
    )
    _remember(secret, user)
    return user


def require_roles(*allowed: str):
    async def guard(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for your account type")
        return user
    return guard


require_admin = require_roles(ROLE_ADMIN)
require_commercial = require_roles(ROLE_COMMERCIAL)
require_reports = require_roles(ROLE_COMMERCIAL, ROLE_ADMIN)
require_items = require_roles(ROLE_SALES, ROLE_COMMERCIAL, ROLE_ADMIN)
