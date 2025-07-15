from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
import redis.asyncio as redis

from src.auth.dependencies import get_current_user, oauth2_scheme
from src.auth.tokens import create_access_token, create_refresh_token, decode_token
from src.users.models import User
from src.database import get_async_session
from sqlalchemy.future import select
from src.config import REDIS_HOST, REDIS_PORT

templates = Jinja2Templates(directory="src/templates")

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
redis = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.post("/login")
async def login(
    request: Request, 
    form_data: OAuth2PasswordRequestForm = Depends(), 
    session: AsyncSession = Depends(get_async_session
)):
    stmt = select(User).where(User.email == form_data.username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    await redis.set(f"refresh_token:{user.id}", refresh_token)

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="Authorization",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=1800,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="Lax",
        max_age=604800,
        path="/",
    )
    return response

@router.post("/refresh")
async def refresh_token(request: Request):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        saved_token = await redis.get(f"refresh_token:{user_id}")
        if saved_token != token:
            raise HTTPException(status_code=401, detail="Token mismatch")

        new_access = create_access_token({"sub": str(user_id)})
        new_refresh = create_refresh_token({"sub": str(user_id)})
        await redis.set(f"refresh_token:{user_id}", new_refresh)

        response = JSONResponse(content={"message": "Token refreshed"})
        response.set_cookie("Authorization", f"Bearer {new_access}", httponly=True, secure=True, samesite="Lax", max_age=1800)
        response.set_cookie("refresh_token", new_refresh, httponly=True, secure=True, samesite="Lax", max_age=604800)
        return response
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "default_rate": float(user.default_rate)
    }

@router.get("/logout")
async def logout_page(request: Request, token: str = Depends(oauth2_scheme)):
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        await redis.delete(f"refresh_token:{user_id}")
    except:
        pass

    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("Authorization")
    return response
