from decimal import Decimal
from fastapi import APIRouter, Form, HTTPException, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import date, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.payouts.models import Payout, RoleType
from src.tiktok.shifts.models import Shift
from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.tiktok.reports.service import get_half_month_periods, get_weekly_periods, get_monthly_report, get_payouts_for_period, summarize_period
from src.users.models import User
from src.payouts.models import Location

from src.tasks.reporting import _build_period_for_today, _generate_and_send_reports

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/monthly", response_class=HTMLResponse)
async def monthly_report_page(
    request: Request,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None),
    period_mode: str = Query("new", regex="^(old|new|custom)$"),  # new - 4 периода, old - 2 периода, custom - произвольный
    custom_start: date = Query(None),
    custom_end: date = Query(None),
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

    users_q = await session.execute(select(User))
    users = users_q.scalars().all()

    user_map = {u.id: u.name for u in users}

    # Выбор логики периодов
    if period_mode == "custom":
        # Произвольный период
        if not custom_start or not custom_end:
            # Если даты не указаны, показываем текущий месяц в режиме new
            period_mode = "new"
        elif custom_start > custom_end:
            raise HTTPException(status_code=400, detail="Дата начала не может быть позже даты окончания")
        else:
            data_custom = await get_monthly_report(session, custom_start, custom_end, current_user=user)
            payouts_custom = await get_payouts_for_period(session, custom_start, custom_end, current_user=user)
            custom_summary = summarize_period(data_custom, payouts_custom)

            periods = [
                (f"{custom_start.day}.{custom_start.month}–{custom_end.day}.{custom_end.month}", custom_summary, (custom_start, custom_end))
            ]

            return templates.TemplateResponse("tiktok/reports/monthly.html", {
                "request": request,
                "user": user,
                "user_map": user_map,
                "year": year or custom_start.year,
                "month": month or custom_start.month,
                "period_mode": period_mode,
                "periods": periods,
                "custom_start": custom_start,
                "custom_end": custom_end,
            })

    if period_mode == "old":
        # Старая логика: 1-15, 16-конец
        first_half, second_half = get_half_month_periods(month, year)

        data_1_15 = await get_monthly_report(session, first_half[0], first_half[1], current_user=user)
        data_16_31 = await get_monthly_report(session, second_half[0], second_half[1], current_user=user)

        payouts_1_15 = await get_payouts_for_period(session, first_half[0], first_half[1], current_user=user)
        payouts_16_31 = await get_payouts_for_period(session, second_half[0], second_half[1], current_user=user)

        first_half_summary = summarize_period(data_1_15, payouts_1_15)
        second_half_summary = summarize_period(data_16_31, payouts_16_31)

        periods = [
            ("1–15", first_half_summary, first_half),
            ("16–конец", second_half_summary, second_half)
        ]
    else:
        # Новая логика: 1-7, 8-14, 15-21, 22-конец
        period1, period2, period3, period4 = get_weekly_periods(month, year)

        data_1_7 = await get_monthly_report(session, period1[0], period1[1], current_user=user)
        data_8_14 = await get_monthly_report(session, period2[0], period2[1], current_user=user)
        data_15_21 = await get_monthly_report(session, period3[0], period3[1], current_user=user)
        data_22_end = await get_monthly_report(session, period4[0], period4[1], current_user=user)

        payouts_1_7 = await get_payouts_for_period(session, period1[0], period1[1], current_user=user)
        payouts_8_14 = await get_payouts_for_period(session, period2[0], period2[1], current_user=user)
        payouts_15_21 = await get_payouts_for_period(session, period3[0], period3[1], current_user=user)
        payouts_22_end = await get_payouts_for_period(session, period4[0], period4[1], current_user=user)

        period1_summary = summarize_period(data_1_7, payouts_1_7)
        period2_summary = summarize_period(data_8_14, payouts_8_14)
        period3_summary = summarize_period(data_15_21, payouts_15_21)
        period4_summary = summarize_period(data_22_end, payouts_22_end)

        periods = [
            ("1–7", period1_summary, period1),
            ("8–14", period2_summary, period2),
            ("15–21", period3_summary, period3),
            (f"22–{period4[1].day}", period4_summary, period4)
        ]

    return templates.TemplateResponse("tiktok/reports/monthly.html", {
        "request": request,
        "user": user,
        "user_map": user_map,
        "year": year,
        "month": month,
        "period_mode": period_mode,
        "periods": periods,
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
        location=Location.TikTok,
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


@router.get("/telegram", response_class=HTMLResponse)
async def telegram_report_form(
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    success: bool | None = Query(False),
    user: User = Depends(get_admin_user),
):
    today = date.today()
    default_period = _build_period_for_today(today) or (today.replace(day=1), today)
    start_date = start or default_period[0]
    end_date = end or default_period[1]

    return templates.TemplateResponse(
        "tiktok/reports/telegram_manual.html",
        {
            "request": request,
            "user": user,
            "start": start_date,
            "end": end_date,
            "success": bool(success),
        },
    )


@router.post("/telegram", response_class=HTMLResponse)
async def send_telegram_report(
    request: Request,
    start: date = Form(...),
    end: date = Form(...),
    user: User = Depends(get_admin_user),
):
    if start > end:
        return templates.TemplateResponse(
            "tiktok/reports/telegram_manual.html",
            {
                "request": request,
                "user": user,
                "start": start,
                "end": end,
                "error": "Дата начала не может быть позже даты окончания.",
                "success": False,
            },
            status_code=400,
        )

    await _generate_and_send_reports(start, end)

    redirect_url = f"/reports/telegram?start={start.isoformat()}&end={end.isoformat()}&success=true"
    return RedirectResponse(redirect_url, status_code=303)
