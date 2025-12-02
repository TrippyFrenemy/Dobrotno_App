from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta
from decimal import Decimal

from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.database import get_async_session
from src.users.models import User
from src.utils.csrf import generate_csrf_token, verify_csrf_token
from src.tiktok.orders.models import Order
from .models import OrderType
from .schemas import OrderTypeCreate, OrderTypeUpdate

router = APIRouter(prefix="/order-types", tags=["Order Types"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(get_manager_or_admin)])
async def list_order_types(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_manager_or_admin),
):
    """Список всех типов заказов"""
    csrf_token = await generate_csrf_token(current_user.id)

    stmt = select(OrderType).order_by(OrderType.name)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    return templates.TemplateResponse(
        "tiktok/order_types/list.html",
        {"request": request, "order_types": order_types, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.get("/{order_type_id}/stats", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def order_type_stats(
    order_type_id: int,
    request: Request,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None),
    period_mode: str = Query("new", regex="^(new|custom)$"),
    custom_start: date = Query(None),
    custom_end: date = Query(None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Статистика по конкретному типу заказа"""
    from src.tiktok.reports.service import get_weekly_periods

    # Получаем тип заказа
    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    today = date.today()

    # Определяем месяц/год по умолчанию
    if not month or not year:
        if today.day <= 7:
            target = today.replace(day=1) - timedelta(days=1)
        else:
            target = today
        month = target.month
        year = target.year

    # Определяем периоды
    periods = []
    if period_mode == "custom" and custom_start and custom_end:
        if custom_start > custom_end:
            raise HTTPException(status_code=400, detail="Дата начала не может быть позже даты окончания")
        periods = [(f"{custom_start.day}.{custom_start.month}–{custom_end.day}.{custom_end.month}", custom_start, custom_end)]
    else:
        # Недельные периоды
        period1, period2, period3, period4 = get_weekly_periods(month, year)
        periods = [
            ("1–7", period1[0], period1[1]),
            ("8–14", period2[0], period2[1]),
            ("15–21", period3[0], period3[1]),
            (f"22–{period4[1].day}", period4[0], period4[1]),
        ]

    # Собираем статистику по каждому периоду
    periods_data = []
    for title, start_date, end_date in periods:
        # Статистика за период
        stmt_stats = select(
            func.count(Order.id).label("total_count"),
            func.sum(Order.amount).label("total_amount"),
            func.avg(Order.amount).label("avg_amount"),
        ).where(
            Order.type_id == order_type_id,
            Order.date >= start_date,
            Order.date <= end_date
        )
        result_stats = await session.execute(stmt_stats)
        stats_row = result_stats.one()

        # Статистика по дням
        stmt_daily = (
            select(
                Order.date,
                func.count(Order.id).label("count"),
                func.sum(Order.amount).label("amount")
            )
            .where(
                Order.type_id == order_type_id,
                Order.date >= start_date,
                Order.date <= end_date
            )
            .group_by(Order.date)
            .order_by(Order.date.desc())
        )
        result_daily = await session.execute(stmt_daily)
        daily_stats = [
            {"date": row.date, "count": row.count, "amount": row.amount}
            for row in result_daily.all()
        ]

        periods_data.append({
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "total_count": stats_row.total_count or 0,
            "total_amount": stats_row.total_amount or Decimal('0'),
            "avg_amount": stats_row.avg_amount or Decimal('0'),
            "daily_stats": daily_stats,
        })

    # Последние заказы этого типа
    stmt_recent = (
        select(Order)
        .where(Order.type_id == order_type_id)
        .order_by(Order.date.desc(), Order.created_at.desc())
        .limit(20)
    )
    result_recent = await session.execute(stmt_recent)
    recent_orders = result_recent.scalars().all()

    return templates.TemplateResponse(
        "tiktok/order_types/stats.html",
        {
            "request": request,
            "current_user": current_user,
            "order_type": order_type,
            "month": month,
            "year": year,
            "period_mode": period_mode,
            "custom_start": custom_start,
            "custom_end": custom_end,
            "periods_data": periods_data,
            "recent_orders": recent_orders,
        },
    )


@router.get("/create", response_class=HTMLResponse, dependencies=[Depends(get_manager_or_admin)])
async def create_order_type_form(
    request: Request,
    current_user: User = Depends(get_manager_or_admin),
):
    """Форма создания нового типа заказа"""
    csrf_token = await generate_csrf_token(current_user.id)

    return templates.TemplateResponse(
        "tiktok/order_types/create.html",
        {"request": request, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.post("/create", dependencies=[Depends(get_manager_or_admin)])
async def create_order_type(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    """Создание нового типа заказа"""
    form_data = await request.form()

    # CSRF проверка
    csrf_token = form_data.get("csrf_token")
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    name = form_data.get("name", "").strip()
    # Менеджеры не могут устанавливать комиссию - используем default 100%
    if user.role == "admin":
        commission_percent = float(form_data.get("commission_percent", 100.0))
    else:
        commission_percent = 100.0
    is_active = form_data.get("is_active") == "on"

    # Проверка на уникальность имени
    stmt = select(OrderType).where(OrderType.name == name)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail=f"Тип заказа '{name}' уже существует")

    # Создание нового типа
    order_type = OrderType(
        name=name,
        commission_percent=commission_percent,
        is_active=is_active,
    )

    session.add(order_type)
    await session.commit()

    return RedirectResponse("/order-types/", status_code=302)


@router.get("/{order_type_id}/edit", response_class=HTMLResponse, dependencies=[Depends(get_manager_or_admin)])
async def edit_order_type_form(
    order_type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_manager_or_admin),
):
    """Форма редактирования типа заказа"""
    csrf_token = await generate_csrf_token(current_user.id)

    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    return templates.TemplateResponse(
        "tiktok/order_types/edit.html",
        {"request": request, "order_type": order_type, "current_user": current_user, "csrf_token": csrf_token},
    )


@router.post("/{order_type_id}/edit", dependencies=[Depends(get_manager_or_admin)])
async def edit_order_type(
    order_type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    """Обновление типа заказа"""
    form_data = await request.form()

    # CSRF проверка
    csrf_token = form_data.get("csrf_token")
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    name = form_data.get("name", "").strip()
    # Менеджеры не могут изменять комиссию - оставляем текущее значение
    if user.role == "admin":
        commission_percent = float(form_data.get("commission_percent", order_type.commission_percent))
    else:
        commission_percent = float(order_type.commission_percent)
    is_active = form_data.get("is_active") == "on"

    # Проверка на уникальность имени (кроме текущего)
    stmt = select(OrderType).where(OrderType.name == name, OrderType.id != order_type_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail=f"Тип заказа '{name}' уже существует")

    # Обновление
    order_type.name = name
    order_type.commission_percent = commission_percent
    order_type.is_active = is_active

    await session.commit()

    return RedirectResponse("/order-types/", status_code=302)


@router.post("/{order_type_id}/delete", dependencies=[Depends(get_admin_user)])
async def delete_order_type(
    order_type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    """Удаление типа заказа (только если нет связанных заказов)"""
    form_data = await request.form()

    # CSRF проверка
    csrf_token = form_data.get("csrf_token")
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    # Проверка на наличие связанных заказов
    # Это будет работать после добавления поля type_id в Order
    # Пока просто помечаем как неактивный
    order_type.is_active = False
    await session.commit()

    return RedirectResponse("/order-types/", status_code=302)
