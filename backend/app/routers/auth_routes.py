from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr

from ..auth import CurrentUser, create_session, current_user, destroy_session
from ..config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str


def _user_payload(user: CurrentUser) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


@router.post("/login")
async def login(body: LoginBody, response: Response):
    secret, user = create_session(body.email, body.password)
    response.set_cookie(
        settings.session_cookie,
        secret,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=60 * 60 * 24 * 7,
        path="/",
    )
    return {"user": _user_payload(user)}


@router.post("/logout")
async def logout(request: Request, response: Response):
    secret = request.cookies.get(settings.session_cookie)
    if secret:
        destroy_session(secret)
    response.delete_cookie(settings.session_cookie, path="/")
    return {"message": "Signed out."}


@router.get("/me")
async def me(user: CurrentUser = Depends(current_user)):
    return {"user": _user_payload(user)}
