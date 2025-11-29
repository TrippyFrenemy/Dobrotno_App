from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import insert, select, delete, extract, and_
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import List, Optional

from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.tiktok.returns.models import Return
from src.tiktok.orders.models import Order
from src.users.models import User, UserRole
from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/create", response_class=HTMLResponse)
async def create_return_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    сsrf_token = await generate_csrf_token(user.id)

    # Загружаем последние заказы для выбора (опционально)
    stmt_orders = select(Order).options(joinedload(Order.created_by_user)).order_by(Order.date.desc()).limit(100)
    result_orders = await session.execute(stmt_orders)
    orders = result_orders.scalars().all()

    # Загружаем сотрудников для назначения штрафов
    stmt_users = select(User).where(
        User.is_active == True,
        User.role == UserRole.EMPLOYEE
    ).order_by(User.name)
    result_users = await session.execute(stmt_users)
    employees = result_users.scalars().all()

    return templates.TemplateResponse("tiktok/returns/create.html", {
        "request": request,
        "csrf_token": сsrf_token,
        "orders": orders,
        "employees": employees
    })

@router.post("/create")
async def create_return(
    date_: date = Form(...),
    amount: Decimal = Form(...),
    reason: str = Form(""),
    order_id: int = Form(None),
    penalty_amount: Decimal = Form(Decimal("0.0")),
    selected_employees: List[int] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата возврата должна быть в пределах 14 дней от сегодняшней")

    # Валидация: если указан штраф, должен быть выбран хотя бы один сотрудник
    if penalty_amount > 0 and not selected_employees:
        raise HTTPException(status_code=400, detail="Если указан штраф, необходимо выбрать хотя бы одного сотрудника")

    # Строим penalty_distribution: делим штраф поровну между выбранными сотрудниками
    penalty_distribution = {}
    if penalty_amount > 0 and selected_employees:
        penalty_per_employee = (penalty_amount / len(selected_employees)).quantize(
            Decimal('0.01'),
            rounding=ROUND_CEILING
        )
        for emp_id in selected_employees:
            penalty_distribution[str(emp_id)] = float(penalty_per_employee)

    stmt = insert(Return).values(
        date=date_,
        amount=amount,
        reason=reason,
        order_id=order_id if order_id else None,
        penalty_amount=penalty_amount,
        penalty_distribution=penalty_distribution,
        created_by=user.id
    )
    await session.execute(stmt)
    await session.commit()
    return RedirectResponse("/dashboard", status_code=302)

@router.get("/all/list", response_class=HTMLResponse)
async def list_returns_all(
    request: Request,
    day: Optional[int] = Query(date.today().day),
    month: Optional[int] = Query(date.today().month),
    year: Optional[int] = Query(date.today().year),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user)
):
    filters = [
        extract("day", Return.date) == day,
        extract("month", Return.date) == month,
        extract("year", Return.date) == year
    ]

    stmt = select(Return).where(and_(*filters)).options(
        joinedload(Return.created_by_user),
        joinedload(Return.order)
    )

    # Применяем сортировку
    if sort_by == "date_desc":
        stmt = stmt.order_by(Return.date.desc(), Return.created_at.desc())
    elif sort_by == "date_asc":
        stmt = stmt.order_by(Return.date.asc(), Return.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(Return.created_at.desc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(Return.created_at.asc())
    elif sort_by == "amount_desc":
        stmt = stmt.order_by(Return.amount.desc())
    elif sort_by == "amount_asc":
        stmt = stmt.order_by(Return.amount.asc())
    elif sort_by == "penalty_desc":
        stmt = stmt.order_by(Return.penalty_amount.desc())
    elif sort_by == "penalty_asc":
        stmt = stmt.order_by(Return.penalty_amount.asc())
    else:
        stmt = stmt.order_by(Return.date.desc())

    result = await session.execute(stmt)
    returns = result.scalars().all()

    return templates.TemplateResponse("tiktok/returns/list.html", {
        "request": request,
        "returns": returns,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "sort_by": sort_by,
    })

@router.get("/{user_id}/list", response_class=HTMLResponse)
async def list_returns_user(
    user_id: int,
    request: Request,
    day: Optional[int] = Query(date.today().day),
    month: Optional[int] = Query(date.today().month),
    year: Optional[int] = Query(date.today().year),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    filters = [
        Return.created_by == user.id,
        extract("day", Return.date) == day,
        extract("month", Return.date) == month,
        extract("year", Return.date) == year
    ]

    stmt = select(Return).where(and_(*filters)).options(
        joinedload(Return.created_by_user),
        joinedload(Return.order)
    )

    # Применяем сортировку
    if sort_by == "date_desc":
        stmt = stmt.order_by(Return.date.desc(), Return.created_at.desc())
    elif sort_by == "date_asc":
        stmt = stmt.order_by(Return.date.asc(), Return.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(Return.created_at.desc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(Return.created_at.asc())
    elif sort_by == "amount_desc":
        stmt = stmt.order_by(Return.amount.desc())
    elif sort_by == "amount_asc":
        stmt = stmt.order_by(Return.amount.asc())
    elif sort_by == "penalty_desc":
        stmt = stmt.order_by(Return.penalty_amount.desc())
    elif sort_by == "penalty_asc":
        stmt = stmt.order_by(Return.penalty_amount.asc())
    else:
        stmt = stmt.order_by(Return.date.desc())

    result = await session.execute(stmt)
    returns = result.scalars().all()

    return templates.TemplateResponse("tiktok/returns/list.html", {
        "request": request,
        "returns": returns,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "sort_by": sort_by,
    })

@router.get("/{return_id}/edit", response_class=HTMLResponse)
async def edit_return_page(
    return_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    сsrf_token = await generate_csrf_token(user.id)

    ret = await session.get(Return, return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="Возврат не найден")

    # Загружаем последние заказы для выбора (опционально)
    stmt_orders = select(Order).options(joinedload(Order.created_by_user)).order_by(Order.date.desc()).limit(100)
    result_orders = await session.execute(stmt_orders)
    orders = result_orders.scalars().all()

    # Загружаем сотрудников для назначения штрафов
    stmt_users = select(User).where(User.is_active == True).order_by(User.name)
    result_users = await session.execute(stmt_users)
    employees = result_users.scalars().all()

    # Извлекаем список ID сотрудников с штрафами из penalty_distribution
    penalized_employee_ids = []
    if ret.penalty_distribution:
        penalized_employee_ids = [int(emp_id) for emp_id in ret.penalty_distribution.keys()]

    return templates.TemplateResponse("tiktok/returns/edit.html", {
        "request": request,
        "ret": ret,
        "csrf_token": сsrf_token,
        "orders": orders,
        "employees": employees,
        "penalized_employee_ids": penalized_employee_ids
    })

@router.post("/{return_id}/edit", response_class=RedirectResponse)
async def update_return(
    return_id: int,
    date_: date = Form(...),
    amount: Decimal = Form(...),
    reason: str = Form(""),
    order_id: int = Form(None),
    penalty_amount: Decimal = Form(Decimal("0.0")),
    selected_employees: List[int] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата возврата должна быть в пределах 14 дней от сегодняшней")

    ret = await session.get(Return, return_id)
    if not ret:
        raise HTTPException(status_code=404, detail="Возврат не найден")

    # Валидация: если указан штраф, должен быть выбран хотя бы один сотрудник
    if penalty_amount > 0 and not selected_employees:
        raise HTTPException(status_code=400, detail="Если указан штраф, необходимо выбрать хотя бы одного сотрудника")

    # Строим penalty_distribution: делим штраф поровну между выбранными сотрудниками
    penalty_distribution = {}
    if penalty_amount > 0 and selected_employees:
        penalty_per_employee = penalty_amount / len(selected_employees)
        for emp_id in selected_employees:
            penalty_distribution[str(emp_id)] = float(penalty_per_employee)

    ret.date = date_
    ret.amount = amount
    ret.reason = reason
    ret.order_id = order_id if order_id else None
    ret.penalty_amount = penalty_amount
    ret.penalty_distribution = penalty_distribution
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
