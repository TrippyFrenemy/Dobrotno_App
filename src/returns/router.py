from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import insert, select, delete
from datetime import date
from decimal import Decimal

from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.returns.models import Return
from src.users.models import User
from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/create", response_class=HTMLResponse)
async def create_return_page(request: Request, user: User = Depends(get_manager_or_admin)):
    сsrf_token = await generate_csrf_token(user.id)
    return templates.TemplateResponse("returns/create.html", {"request": request, "csrf_token": сsrf_token})

@router.post("/create")
async def create_return(
    date_: date = Form(...),
    amount: Decimal = Form(...),
    reason: str = Form(""),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата возврата должна быть в пределах 14 дней от сегодняшней")

    stmt = insert(Return).values(
        date=date_,
        amount=amount,
        reason=reason,
        created_by=user.id
    )
    await session.execute(stmt)
    await session.commit()
    return RedirectResponse("/dashboard", status_code=302)

@router.get("/all/list", response_class=HTMLResponse)
async def list_returns_all(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user)
):
    stmt = select(Return).options(joinedload(Return.created_by_user)).order_by(Return.date.desc())
    result = await session.execute(stmt)
    returns = result.scalars().all()
    return templates.TemplateResponse("returns/list.html", {"request": request, "returns": returns, "user": user})

@router.get("/{user_id}/list", response_class=HTMLResponse)
async def list_returns_user(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    stmt = select(Return).where(Return.created_by == user.id).order_by(Return.date.desc())
    result = await session.execute(stmt)
    returns = result.scalars().all()
    return templates.TemplateResponse("returns/list.html", {"request": request, "returns": returns, "user": user})

@router.get("/{return_id}/edit", response_class=HTMLResponse)
async def edit_return_page(return_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_manager_or_admin)):
    сsrf_token = await generate_csrf_token(user.id)

    ret = await session.get(Return, return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="Возврат не найден")
    return templates.TemplateResponse("returns/edit.html", {"request": request, "ret": ret, "csrf_token": сsrf_token})

@router.post("/{return_id}/edit", response_class=RedirectResponse)
async def update_return(
    return_id: int,
    date_: date = Form(...),
    amount: Decimal = Form(...),
    reason: str = Form(""),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    if abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата возврата должна быть в пределах 14 дней от сегодняшней")

    ret = await session.get(Return, return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="Возврат не найден")

    ret.date = date_
    ret.amount = amount
    ret.reason = reason
    await session.commit()

    if user.role == "admin":
        return RedirectResponse("/returns/all/list", status_code=302)
    return RedirectResponse(f"/returns/{user.id}/list", status_code=302)

@router.post("/{return_id}/delete", response_class=RedirectResponse)
async def delete_return(return_id: int, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    await session.execute(delete(Return).where(Return.id == return_id))
    await session.commit()
    if user.role == "admin":
        return RedirectResponse("/returns/all/list", status_code=302)
    return RedirectResponse(f"/returns/{user.id}/list", status_code=302)
