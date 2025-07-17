from decimal import Decimal
from fastapi import APIRouter, Form, HTTPException, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import date, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.payouts.models import Payout, RoleType
from src.shifts.models import Shift, ShiftLocation
from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.reports.service import get_half_month_periods, get_monthly_report, get_payouts_for_period
from src.users.models import User

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/monthly", response_class=HTMLResponse)
async def monthly_report_page(
    request: Request,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None),
    session: AsyncSession = Depends(get_async_session),
    user = Depends(get_manager_or_admin),
):
    today = date.today()

    # Выбор по умолчанию: текущий или предыдущий месяц
    if not month or not year:
        if today.day <= 7:
            target = today.replace(day=1) - timedelta(days=1)
        else:
            target = today
        month = target.month
        year = target.year

    first_half, second_half = get_half_month_periods(month, year)

    users_q = await session.execute(select(User))
    users = users_q.scalars().all()
    
    user_map = {u.id: u.name for u in users}

    # Сбор данных за обе половины
    data_1_15 = await get_monthly_report(session, first_half[0], first_half[1], current_user=user)
    data_16_31 = await get_monthly_report(session, second_half[0], second_half[1], current_user=user)

    payouts_1_15 = await get_payouts_for_period(session, first_half[0], first_half[1], current_user=user)
    payouts_16_31 = await get_payouts_for_period(session, second_half[0], second_half[1], current_user=user)

    return templates.TemplateResponse("reports/monthly.html", {
        "request": request,
        "user": user,
        "user_map": user_map,
        "year": year,
        "month": month,
        "first_half": data_1_15,
        "second_half": data_16_31,
        "payouts_1_15": payouts_1_15,
        "payouts_16_31": payouts_16_31,
        "first_half_range": first_half,
        "second_half_range": second_half,
    })

@router.post("/pay")
async def make_payout(
    user_id: int = Form(...),
    date: date = Form(...),
    amount: Decimal = Form(...),
    session: AsyncSession = Depends(get_async_session),
    payer_user: User = Depends(get_manager_or_admin)
):
    # получаем user
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # определяем роль (выплачиваем как EMPLOYEE/MANAGER/ADMIN)
    role_type = RoleType(user.role.value)
    payout = Payout(
        user_id=user_id,
        date=date,
        location=ShiftLocation.tiktok,
        role_type=role_type,
        amount=amount,
        paid_at=datetime.utcnow(),
        is_manual=True
    )
    session.add(payout)
    await session.commit()

    # result = await session.execute(select(Shift).where(Shift.date == date))
    # shift = result.scalar_one_or_none()
    # if not shift:
    #     return RedirectResponse(f"/shifts/create?date={date.isoformat()}", status_code=302)
    
    return RedirectResponse(f"/reports/monthly?month={date.month}&year={date.year}", status_code=302)

