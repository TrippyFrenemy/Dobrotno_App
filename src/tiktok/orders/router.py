from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, delete, extract, insert, select
from sqlalchemy.orm import joinedload
from datetime import date, datetime
from decimal import Decimal
import json

from src.tiktok.shifts.models import Shift
from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.tiktok.orders.models import Order, OrderOrderType
from src.tiktok.orders.schemas import OrderCreate, OrderTypeItem
from src.tiktok.orders import service as order_service
from src.tiktok.order_types.models import OrderType
from src.users.models import User
from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/create", response_class=HTMLResponse)
async def create_order_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    csrf_token = await generate_csrf_token(user.id)

    # Получаем активные типы заказов
    stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/create.html", {
        "request": request,
        "csrf_token": csrf_token,
        "order_types": order_types
    })

@router.post("/create")
async def create_order_endpoint(
    request: Request,
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    order_types_json: str = Form(..., alias="order_types"),  # JSON string from form
    csrf_token: str = Form(...),
    confirm: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not order_types_json or not order_types_json.strip():
        raise HTTPException(status_code=400, detail="Order types are required")

    # Parse order types from JSON
    try:
        order_types_data = json.loads(order_types_json)
        order_types = [OrderTypeItem(**ot) for ot in order_types_data]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid order types data: {str(e)}")

    # Validate using schema
    try:
        order_data = OrderCreate(
            phone_number=phone_number,
            date=date_,
            amount=amount,
            order_types=order_types
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    # Check for duplicates
    duplicates = await order_service.check_duplicates(
        session=session,
        phone_number=phone_number,
        date_=date_,
        amount=amount,
        order_types=order_types
    )

    # If duplicates found and not confirmed, show confirmation page
    if (duplicates["exact_duplicate"] or duplicates["similar_orders"]) and confirm != "yes":
        # Load order type names for display
        type_ids = [ot.order_type_id for ot in order_types]
        stmt = select(OrderType).where(OrderType.id.in_(type_ids))
        result = await session.execute(stmt)
        types_dict = {ot.id: ot for ot in result.scalars().all()}

        # Prepare new order types for display
        new_order_types = [
            {
                "order_type_id": ot.order_type_id,
                "amount": ot.amount,
                "type_name": types_dict[ot.order_type_id].name if ot.order_type_id in types_dict else "Unknown"
            }
            for ot in order_types
        ]

        return templates.TemplateResponse("tiktok/orders/confirm_duplicate.html", {
            "request": request,
            "phone_number": phone_number,
            "date_": date_.isoformat(),
            "amount": amount,
            "order_types_json": order_types_json,
            "new_order_types": new_order_types,
            "exact_duplicate": duplicates["exact_duplicate"],
            "similar_orders": duplicates["similar_orders"],
            "csrf_token": await generate_csrf_token(user.id),
        })

    # Create order
    try:
        new_order = await order_service.create_order(
            session=session,
            order_data=order_data,
            user_id=user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check if shift exists for this date
    result = await session.execute(select(Shift).where(Shift.date == date_))
    shift = result.scalar_one_or_none()
    if not shift:
        return RedirectResponse(f"/shifts/create?date={date_.isoformat()}", status_code=302)

    response = RedirectResponse("/dashboard?success=1", status_code=302)
    response.set_cookie("last_order_info", f"{phone_number},{date_.isoformat()},{amount}", max_age=10)
    return response

@router.get("/all/list", response_class=HTMLResponse)
async def list_orders_all(
    request: Request,
    day: Optional[int] = Query(date.today().day),
    month: Optional[int] = Query(date.today().month),
    year: Optional[int] = Query(date.today().year),
    type_id: Optional[int] = Query(None),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    filters = [
        extract("day", Order.date) == day,
        extract("month", Order.date) == month,
        extract("year", Order.date) == year
    ]

    # Фильтр по типу заказа
    if type_id is not None:
        filters.append(Order.type_id == type_id)

    stmt = select(Order).where(and_(*filters)).options(
        joinedload(Order.created_by_user),
        joinedload(Order.order_type)
    )

    # Применяем сортировку
    if sort_by == "date_desc":
        stmt = stmt.order_by(Order.date.desc(), Order.created_at.desc())
    elif sort_by == "date_asc":
        stmt = stmt.order_by(Order.date.asc(), Order.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(Order.created_at.desc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(Order.created_at.asc())
    elif sort_by == "amount_desc":
        stmt = stmt.order_by(Order.amount.desc())
    elif sort_by == "amount_asc":
        stmt = stmt.order_by(Order.amount.asc())
    else:
        stmt = stmt.order_by(Order.date.desc())

    result = await session.execute(stmt)
    orders = result.scalars().all()

    # Загружаем все типы заказов для фильтра
    types_stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    types_result = await session.execute(types_stmt)
    order_types = types_result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/list.html", {
        "request": request,
        "orders": orders,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "type_id": type_id,
        "sort_by": sort_by,
        "order_types": order_types,
    })


@router.get("/{id}/list", response_class=HTMLResponse)
async def list_orders_user(
    id: int,
    request: Request,
    day: Optional[int] = Query(date.today().day),
    month: Optional[int] = Query(date.today().month),
    year: Optional[int] = Query(date.today().year),
    type_id: Optional[int] = Query(None),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if user.id != id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Нет доступа к чужим заказам")

    filters = [
        Order.created_by == id,
        extract("day", Order.date) == day,
        extract("month", Order.date) == month,
        extract("year", Order.date) == year
    ]

    # Фильтр по типу заказа
    if type_id is not None:
        filters.append(Order.type_id == type_id)

    stmt = select(Order).where(and_(*filters)).options(
        joinedload(Order.created_by_user),
        joinedload(Order.order_type)
    )

    # Применяем сортировку
    if sort_by == "date_desc":
        stmt = stmt.order_by(Order.date.desc(), Order.created_at.desc())
    elif sort_by == "date_asc":
        stmt = stmt.order_by(Order.date.asc(), Order.created_at.asc())
    elif sort_by == "created_at_desc":
        stmt = stmt.order_by(Order.created_at.desc())
    elif sort_by == "created_at_asc":
        stmt = stmt.order_by(Order.created_at.asc())
    elif sort_by == "amount_desc":
        stmt = stmt.order_by(Order.amount.desc())
    elif sort_by == "amount_asc":
        stmt = stmt.order_by(Order.amount.asc())
    else:
        stmt = stmt.order_by(Order.date.desc())

    result = await session.execute(stmt)
    orders = result.scalars().all()

    # Загружаем все типы заказов для фильтра
    types_stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    types_result = await session.execute(types_stmt)
    order_types = types_result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/list.html", {
        "request": request,
        "orders": orders,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "type_id": type_id,
        "sort_by": sort_by,
        "order_types": order_types,
    })


@router.get("/{order_id}/edit", response_class=HTMLResponse)
async def edit_order_page(
    order_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    сsrf_token = await generate_csrf_token(user.id)
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Получаем активные типы заказов
    stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    result = await session.execute(stmt)
    order_types = result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/edit.html", {
        "request": request,
        "order": order,
        "order_types": order_types,
        "user": user,
        "csrf_token": сsrf_token
    })


@router.post("/{order_id}/edit", response_class=RedirectResponse)
async def update_order_endpoint(
    order_id: int,
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    order_types_json: str = Form(..., alias="order_types"),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    if not order_types_json or not order_types_json.strip():
        raise HTTPException(status_code=400, detail="Order types are required")

    # Parse order types from JSON
    try:
        order_types_data = json.loads(order_types_json)
        order_types = [OrderTypeItem(**ot) for ot in order_types_data]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid order types data: {str(e)}")

    # Validate using schema
    try:
        order_data = OrderCreate(
            phone_number=phone_number,
            date=date_,
            amount=amount,
            order_types=order_types
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Update order
    try:
        await order_service.update_order(
            session=session,
            order_id=order_id,
            phone_number=phone_number,
            date_=date_,
            amount=amount,
            order_types=order_types
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if user.role == "admin":
        return RedirectResponse(url="/orders/all/list", status_code=302)
    else:
        return RedirectResponse(url=f"/orders/{user.id}/list", status_code=302)



@router.post("/{order_id}/delete", response_class=RedirectResponse)
async def delete_order(
    order_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    await session.execute(delete(Order).where(Order.id == order_id))
    await session.commit()
    if user.role == "admin":
        return RedirectResponse("/orders/all/list", status_code=302)
    return RedirectResponse(f"/orders/{user.id}/list", status_code=302)
