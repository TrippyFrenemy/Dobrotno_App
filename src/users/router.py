from datetime import time, date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract
from passlib.context import CryptContext
from decimal import Decimal
from collections import defaultdict

from src.auth.dependencies import get_admin_user, get_current_user
from src.users import schemas
from src.users.models import User, UserRole
from src.database import get_async_session
from sqlalchemy.future import select
from src.tiktok.returns.models import Return
from src.tiktok.shifts.models import Shift, ShiftAssignment

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
    shift_start: str = Form("09:00"),
    shift_end: str = Form("20:00"),
    can_take_vacation: Optional[bool] = Form(False),
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
        shift_start=time.fromisoformat(shift_start),
        shift_end=time.fromisoformat(shift_end),
        can_take_vacation=can_take_vacation,
        hashed_password=pwd_context.hash(password),
    )
    session.add(new_user)
    await session.commit()
    return RedirectResponse("/users/me", status_code=302)

@router.get("/me", response_class=HTMLResponse)
async def my_account_page(request: Request, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_async_session)):
    stmt = select(User).where(User.id != user.id)
    result = await session.execute(stmt)
    other_users = result.scalars().all()
    return templates.TemplateResponse("users/me.html", {"request": request, "user": user, "users": other_users})


@router.get("/cabinet", response_class=HTMLResponse)
async def employee_cabinet(
    request: Request,
    months: int = Query(3, ge=1, le=12),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session)
):
    """Личный кабинет сотрудника с зарплатой и штрафами"""

    # Получаем данные за последние N месяцев
    monthly_data = []
    today = date.today()

    for i in range(months):
        # Вычисляем месяц и год
        target_date = today - timedelta(days=30 * i)
        month = target_date.month
        year = target_date.year

        # Период месяца
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # Зарплата за смены (сотрудники)
        shifts_salary = Decimal('0')
        if user.role == UserRole.EMPLOYEE:
            stmt_shifts = (
                select(ShiftAssignment)
                .join(Shift)
                .where(
                    ShiftAssignment.user_id == user.id,
                    Shift.date >= start_date,
                    Shift.date <= end_date
                )
            )
            result_shifts = await session.execute(stmt_shifts)
            assignments = result_shifts.scalars().all()
            shifts_salary = sum(a.salary for a in assignments)

        # Штрафы за месяц
        stmt_returns = (
            select(Return)
            .where(
                Return.date >= start_date,
                Return.date <= end_date
            )
        )
        result_returns = await session.execute(stmt_returns)
        all_returns = result_returns.scalars().all()

        penalties = Decimal('0')
        for ret in all_returns:
            if ret.penalty_distribution and str(user.id) in ret.penalty_distribution:
                penalties += Decimal(str(ret.penalty_distribution[str(user.id)]))

        # Для менеджеров/админов - используем данные из отчетов
        # (упрощенная версия, полные данные в месячных отчетах)
        manager_salary = Decimal('0')
        if user.role in [UserRole.MANAGER, UserRole.ADMIN]:
            # Это упрощенная калькуляция, реальная логика в reports/service.py
            # Для полной точности нужно использовать get_monthly_report
            working_days = 0
            stmt_days = (
                select(func.count(func.distinct(Shift.date)))
                .where(
                    Shift.date >= start_date,
                    Shift.date <= end_date
                )
            )
            result_days = await session.execute(stmt_days)
            working_days = result_days.scalar() or 0
            manager_salary = Decimal(str(user.default_rate)) * working_days

        total_salary = shifts_salary + manager_salary - penalties

        monthly_data.append({
            "month": month,
            "year": year,
            "month_name": ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][month],
            "shifts_salary": shifts_salary,
            "manager_salary": manager_salary,
            "penalties": penalties,
            "total": total_salary,
        })

    # Последние штрафы
    stmt_recent_penalties = (
        select(Return)
        .where(Return.date >= today - timedelta(days=90))
        .order_by(Return.date.desc())
    )
    result_penalties = await session.execute(stmt_recent_penalties)
    all_recent_returns = result_penalties.scalars().all()

    recent_penalties = []
    for ret in all_recent_returns:
        if ret.penalty_distribution and str(user.id) in ret.penalty_distribution:
            recent_penalties.append({
                "date": ret.date,
                "amount": Decimal(str(ret.penalty_distribution[str(user.id)])),
                "reason": ret.reason or "Не указана",
            })

    return templates.TemplateResponse(
        "users/cabinet.html",
        {
            "request": request,
            "user": user,
            "months": months,
            "monthly_data": monthly_data,
            "recent_penalties": recent_penalties[:10],  # Показываем последние 10
        },
    )


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
    shift_start: str = Form("09:00"),
    shift_end: str = Form("20:00"),
    can_take_vacation: Optional[bool] = Form(False),
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
    user.can_take_vacation = can_take_vacation
    user.is_active = is_active
    user.shift_start = time.fromisoformat(shift_start)
    user.shift_end = time.fromisoformat(shift_end)
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
    