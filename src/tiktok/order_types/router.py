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
from src.utils.csrf import verify_csrf_token
from src.tiktok.orders.models import Order
from .models import OrderType
from .schemas import OrderTypeCreate, OrderTypeUpdate

router = APIRouter(prefix="/order-types", tags=["Order Types"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def list_order_types(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Список всех типов заказов"""
    stmt = select(OrderType).order_by(OrderType.name)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    return templates.TemplateResponse(
        "tiktok/order_types/list.html",
        {"request": request, "order_types": order_types, "current_user": current_user},
    )


@router.get("/{order_type_id}/stats", response_class=HTMLResponse)
async def order_type_stats(
    order_type_id: int,
    request: Request,
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_manager_or_admin),
):
    """Статистика по конкретному типу заказа"""
    # Получаем тип заказа
    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    # Определяем период
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    # Общая статистика за период
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

    total_count = stats_row.total_count or 0
    total_amount = stats_row.total_amount or Decimal('0')
    avg_amount = stats_row.avg_amount or Decimal('0')

    # Последние заказы этого типа
    stmt_recent = (
        select(Order)
        .where(Order.type_id == order_type_id)
        .order_by(Order.date.desc(), Order.created_at.desc())
        .limit(20)
    )
    result_recent = await session.execute(stmt_recent)
    recent_orders = result_recent.scalars().all()

    # Статистика по дням за последние N дней
    from sqlalchemy import extract
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
        {
            "date": row.date,
            "count": row.count,
            "amount": row.amount
        }
        for row in result_daily.all()
    ]

    return templates.TemplateResponse(
        "tiktok/order_types/stats.html",
        {
            "request": request,
            "current_user": current_user,
            "order_type": order_type,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "total_count": total_count,
            "total_amount": total_amount,
            "avg_amount": avg_amount,
            "recent_orders": recent_orders,
            "daily_stats": daily_stats,
        },
    )


@router.get("/create", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def create_order_type_form(
    request: Request,
    current_user: User = Depends(get_admin_user),
):
    """Форма создания нового типа заказа"""
    return templates.TemplateResponse(
        "tiktok/order_types/create.html",
        {"request": request, "current_user": current_user},
    )


@router.post("/create", dependencies=[Depends(get_admin_user)])
async def create_order_type(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    """Создание нового типа заказа"""
    form_data = await request.form()

    # CSRF проверка
    csrf_token = form_data.get("csrf_token")
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    name = form_data.get("name", "").strip()
    commission_percent = float(form_data.get("commission_percent", 0.0))
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


@router.get("/{order_type_id}/edit", response_class=HTMLResponse, dependencies=[Depends(get_admin_user)])
async def edit_order_type_form(
    order_type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_admin_user),
):
    """Форма редактирования типа заказа"""
    stmt = select(OrderType).where(OrderType.id == order_type_id)
    result = await session.execute(stmt)
    order_type = result.scalar_one_or_none()

    if not order_type:
        raise HTTPException(status_code=404, detail="Тип заказа не найден")

    return templates.TemplateResponse(
        "tiktok/order_types/edit.html",
        {"request": request, "order_type": order_type, "current_user": current_user},
    )


@router.post("/{order_type_id}/edit", dependencies=[Depends(get_admin_user)])
async def edit_order_type(
    order_type_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
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
    commission_percent = float(form_data.get("commission_percent", 0.0))
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
