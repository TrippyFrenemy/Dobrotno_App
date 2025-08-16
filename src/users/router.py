from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from src.auth.dependencies import get_admin_user, get_current_user
from src.users import schemas
from src.users.models import User, UserRole
from src.database import get_async_session
from sqlalchemy.future import select

from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter(tags=["Users"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

templates = Jinja2Templates(directory="src/templates")

@router.get("/create", response_class=HTMLResponse)
async def user_create_page(request: Request, admin: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(admin.id)
    return templates.TemplateResponse("users/create.html", {"request": request, "csrf_token": csrf_token})

@router.post("/create", response_class=HTMLResponse)
async def user_create_form(
    request: Request,
    email: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    default_rate: float = Form(0.0),
    default_percent: float = Form(1.0),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    if not csrf_token or not await verify_csrf_token(admin.id, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    if result.scalar():
        return templates.TemplateResponse("users/create.html", {
            "request": request,
            "error": "Пользователь уже существует"
        })

    new_user = User(
        email=email,
        name=name,
        role=role,
        default_rate=default_rate,
        default_percent=default_percent,
        hashed_password=pwd_context.hash(password),
    )
    session.add(new_user)
    await session.commit()
    return RedirectResponse("/dashboard", status_code=302)

@router.get("/me", response_class=HTMLResponse)
async def my_account_page(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_async_session)):
    stmt = select(User).where(User.id != user.id)
    result = await session.execute(stmt)
    other_users = result.scalars().all()
    return templates.TemplateResponse("users/me.html", {"request": request, "user": user, "users": other_users})

@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(user_id: int, request: Request, session: AsyncSession = Depends(get_async_session), admin: User = Depends(get_admin_user)):
    crsf_token = await generate_csrf_token(admin.id)
    
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse("users/edit.html", {"request": request, "user": user, "csrf_token": crsf_token})

@router.post("/{user_id}/edit", response_class=RedirectResponse)
async def update_user(
    user_id: int,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    default_rate: float = Form(0.0),
    default_percent: float = Form(1.0),
    is_active: Optional[bool] = Form(False),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(admin.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.name = name
    user.email = email
    user.role = role
    user.default_rate = default_rate
    user.default_percent = default_percent
    user.is_active = is_active
    await session.commit()
    return RedirectResponse("/users/me", status_code=302)

@router.post("/{user_id}/delete", response_class=RedirectResponse)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        await session.delete(user)
        await session.commit()
        return RedirectResponse("/users/me", status_code=302)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Нельзя удалить пользователя — он связан с другими данными.")
    