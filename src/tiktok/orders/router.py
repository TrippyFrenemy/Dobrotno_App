from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, delete, extract, insert, select
from sqlalchemy.orm import joinedload
from datetime import date, datetime
from decimal import Decimal

from src.tiktok.shifts.models import Shift
from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.tiktok.orders.models import Order
from src.users.models import User
from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/create", response_class=HTMLResponse)
async def create_order_page(request: Request, user: User = Depends(get_manager_or_admin)):
    csrf_token = await generate_csrf_token(user.id)
    return templates.TemplateResponse("tiktok/orders/create.html", {"request": request, "csrf_token": csrf_token})

@router.post("/create")
async def create_order(
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    if abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    stmt = insert(Order).values(
        phone_number=phone_number,
        date=date_,
        amount=amount,
        created_by=user.id
    )
    await session.execute(stmt)
    await session.commit()

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
    day: Optional[int] = Query(None),
    month: Optional[int] = Query(datetime.today().month),
    year: Optional[int] = Query(datetime.today().year),
    sort_by: str = Query("created_at"),  # "created_at" или "date"
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    filters = [extract("month", Order.date) == month, extract("year", Order.date) == year]
    if day:
        filters.append(extract("day", Order.date) == day)

    stmt = select(Order).where(and_(*filters)).options(joinedload(Order.created_by_user))

    if sort_by == "created_at":
        stmt = stmt.order_by(Order.created_at.desc())
    else:
        stmt = stmt.order_by(Order.date.desc())

    result = await session.execute(stmt)
    orders = result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/list.html", {
        "request": request,
        "orders": orders,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "sort_by": sort_by,
    })


@router.get("/{id}/list", response_class=HTMLResponse)
async def list_orders_user(
    id: int,
    request: Request,
    day: Optional[int] = Query(None),
    month: Optional[int] = Query(datetime.today().month),
    year: Optional[int] = Query(datetime.today().year),
    sort_by: str = Query("created_at"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if user.id != id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Нет доступа к чужим заказам")

    filters = [
        Order.created_by == id,
        extract("month", Order.date) == month,
        extract("year", Order.date) == year
    ]
    if day:
        filters.append(extract("day", Order.date) == day)

    stmt = select(Order).where(and_(*filters))

    if sort_by == "created_at":
        stmt = stmt.order_by(Order.created_at.desc())
    else:
        stmt = stmt.order_by(Order.date.desc())

    result = await session.execute(stmt)
    orders = result.scalars().all()

    return templates.TemplateResponse("tiktok/orders/list.html", {
        "request": request,
        "orders": orders,
        "user": user,
        "day": day,
        "month": month,
        "year": year,
        "sort_by": sort_by,
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
    return templates.TemplateResponse("tiktok/orders/edit.html", {
        "request": request,
        "order": order,
        "user": user,
        "csrf_token": сsrf_token
    })


@router.post("/{order_id}/edit", response_class=RedirectResponse)
async def update_order(
    order_id: int,
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    if abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    order.phone_number = phone_number
    order.date = date_
    order.amount = amount
    await session.commit()
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

