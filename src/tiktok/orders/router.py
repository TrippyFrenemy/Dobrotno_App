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
from src.tiktok.orders.models import Order, OrderOrderType
from src.tiktok.order_types.models import OrderType, UserOrderTypeSetting
from src.users.models import User, UserRole
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
    order_types_db = result.scalars().all()

    # Получаем настройки пользователя для типов заказов (для фильтрации запрещённых)
    settings_stmt = select(UserOrderTypeSetting).where(
        UserOrderTypeSetting.user_id == user.id
    )
    settings_result = await session.execute(settings_stmt)
    user_settings = {s.order_type_id: s for s in settings_result.scalars().all()}

    # Фильтруем типы заказов: убираем те, где is_allowed = False
    # Админ видит все типы (для него ограничения не применяются)
    order_types = []
    for ot in order_types_db:
        setting = user_settings.get(ot.id)
        # Если есть настройка и is_allowed = False, пропускаем (для не-админов)
        if user.role != UserRole.ADMIN and setting and not setting.is_allowed:
            continue
        order_types.append({"id": ot.id, "name": ot.name})

    return templates.TemplateResponse("tiktok/orders/create.html", {
        "request": request,
        "csrf_token": csrf_token,
        "order_types": order_types
    })

@router.post("/create")
async def create_order(
    request: Request,
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    confirm: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Парсим типы заказов из формы (type_id_1, type_amount_1, type_id_2, type_amount_2, ...)
    form_data = await request.form()
    order_types_data = []

    for key in form_data.keys():
        if key.startswith("type_id_"):
            row_id = key.split("_")[-1]
            type_id = form_data.get(key)
            type_amount = form_data.get(f"type_amount_{row_id}")

            if type_id and type_amount:
                order_types_data.append({
                    "type_id": int(type_id),
                    "amount": Decimal(type_amount)
                })

    # Валидация: минимум 1 тип
    if not order_types_data:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один тип заказа")

    # Валидация: сумма типов = общая сумма
    types_sum = sum(item["amount"] for item in order_types_data)
    if abs(types_sum - amount) >= Decimal("0.01"):
        raise HTTPException(status_code=400, detail=f"Сумма типов ({types_sum}) не соответствует общей сумме ({amount})")

    # Валидация: нет дубликатов типов
    type_ids = [item["type_id"] for item in order_types_data]
    if len(type_ids) != len(set(type_ids)):
        raise HTTPException(status_code=400, detail="Нельзя выбрать один тип дважды")

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    # 🔹 Проверка дубликатов (phone + date + amount, типы НЕ учитываются)
    stmt = select(Order).where(
        Order.phone_number == phone_number,
        Order.date == date_,
        Order.amount == amount
    ).options(
        joinedload(Order.created_by_user),
        joinedload(Order.order_order_types).joinedload(OrderOrderType.order_type)
    ).limit(1)
    result = await session.execute(stmt)
    existing_order = result.unique().scalars().first()

    if existing_order and confirm != "yes":
        # Загружаем типы нового заказа для отображения
        new_types = []
        for item in order_types_data:
            ot = await session.get(OrderType, item["type_id"])
            if ot:
                new_types.append({
                    "name": ot.name,
                    "amount": item["amount"],
                    "commission": ot.commission_percent if user.role == "admin" else None
                })

        # Типы существующего заказа
        existing_types = []
        if existing_order.order_order_types:
            # Новая схема
            for oot in existing_order.order_order_types:
                existing_types.append({
                    "name": oot.order_type.name,
                    "amount": oot.amount,
                    "commission": oot.order_type.commission_percent if user.role == "admin" else None
                })
        elif existing_order.order_type:
            # Старая схема
            existing_types.append({
                "name": existing_order.order_type.name,
                "amount": existing_order.amount,
                "commission": existing_order.order_type.commission_percent if user.role == "admin" else None
            })

        creator_name = existing_order.created_by_user.name if existing_order.created_by_user else "Неизвестный"

        return templates.TemplateResponse("tiktok/orders/confirm_duplicate.html", {
            "request": request,
            "phone_number": phone_number,
            "date_": date_.isoformat(),
            "amount": amount,
            "existing_types": existing_types,
            "new_types": new_types,
            "creator_name": creator_name,
            "csrf_token": await generate_csrf_token(user.id),
            "form_data": dict(form_data),  # Передаем все данные формы для повтора
        })

    # 🔹 Создание заказа
    new_order = Order(
        phone_number=phone_number,
        date=date_,
        amount=amount,
        type_id=None,  # Новые заказы не используют старую схему
        created_by=user.id
    )
    session.add(new_order)
    await session.flush()  # Получаем ID заказа

    # Создаем связи с типами
    for item in order_types_data:
        order_order_type = OrderOrderType(
            order_id=new_order.id,
            order_type_id=item["type_id"],
            amount=item["amount"]
        )
        session.add(order_order_type)

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
    day: Optional[int] = Query(date.today().day),
    month: Optional[int] = Query(date.today().month),
    year: Optional[int] = Query(date.today().year),
    type_id: Optional[str] = Query(None),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    # Конвертируем type_id из строки в int (пустая строка -> None)
    type_id_int = int(type_id) if type_id else None

    filters = [
        extract("day", Order.date) == day,
        extract("month", Order.date) == month,
        extract("year", Order.date) == year
    ]

    # Фильтр по типу заказа
    if type_id_int is not None:
        filters.append(Order.type_id == type_id_int)

    stmt = select(Order).where(and_(*filters)).options(
        joinedload(Order.created_by_user),
        joinedload(Order.order_type),
        joinedload(Order.order_order_types).joinedload(OrderOrderType.order_type)
    ).execution_options(populate_existing=True)

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
    orders = result.unique().scalars().all()

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
        "type_id": type_id_int,
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
    type_id: Optional[str] = Query(None),
    sort_by: str = Query("date_desc"),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if user.id != id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Нет доступа к чужим заказам")

    # Конвертируем type_id из строки в int (пустая строка -> None)
    type_id_int = int(type_id) if type_id else None

    filters = [
        Order.created_by == id,
        extract("day", Order.date) == day,
        extract("month", Order.date) == month,
        extract("year", Order.date) == year
    ]

    # Фильтр по типу заказа
    if type_id_int is not None:
        filters.append(Order.type_id == type_id_int)

    stmt = select(Order).where(and_(*filters)).options(
        joinedload(Order.created_by_user),
        joinedload(Order.order_type),
        joinedload(Order.order_order_types).joinedload(OrderOrderType.order_type)
    ).execution_options(populate_existing=True)

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
    orders = result.unique().scalars().all()

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
        "type_id": type_id_int,
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

    # Загружаем заказ с типами (обе схемы)
    stmt = select(Order).where(Order.id == order_id).options(
        joinedload(Order.order_type),
        joinedload(Order.order_order_types).joinedload(OrderOrderType.order_type)
    )
    result = await session.execute(stmt)
    order = result.unique().scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Получаем активные типы заказов
    types_stmt = select(OrderType).where(OrderType.is_active == True).order_by(OrderType.name)
    types_result = await session.execute(types_stmt)
    order_types_db = types_result.scalars().all()

    # Получаем настройки пользователя для типов заказов
    settings_stmt = select(UserOrderTypeSetting).where(
        UserOrderTypeSetting.user_id == user.id
    )
    settings_result = await session.execute(settings_stmt)
    user_settings = {s.order_type_id: s for s in settings_result.scalars().all()}

    # Собираем ID текущих типов заказа (они должны отображаться даже если запрещены)
    current_type_ids = set()
    if order.order_order_types:
        current_type_ids = {oot.order_type_id for oot in order.order_order_types}
    elif order.type_id:
        current_type_ids = {order.type_id}

    # Фильтруем типы заказов: убираем запрещённые (кроме уже выбранных)
    order_types = []
    for ot in order_types_db:
        setting = user_settings.get(ot.id)
        # Если тип уже выбран в заказе — показываем его
        # Иначе проверяем is_allowed (для не-админов)
        if ot.id in current_type_ids:
            order_types.append({"id": ot.id, "name": ot.name})
        elif user.role != UserRole.ADMIN and setting and not setting.is_allowed:
            continue
        else:
            order_types.append({"id": ot.id, "name": ot.name})

    # Подготавливаем текущие типы для отображения
    current_types = []
    if order.order_order_types:
        # Новая схема
        for oot in order.order_order_types:
            current_types.append({
                "type_id": oot.order_type_id,
                "amount": float(oot.amount)
            })
    elif order.type_id:
        # Старая схема - мигрируем в UI
        current_types.append({
            "type_id": order.type_id,
            "amount": float(order.amount)
        })

    return templates.TemplateResponse("tiktok/orders/edit.html", {
        "request": request,
        "order": order,
        "order_types": order_types,
        "current_types": current_types,
        "user": user,
        "csrf_token": сsrf_token
    })


@router.post("/{order_id}/edit", response_class=RedirectResponse)
async def update_order(
    order_id: int,
    request: Request,
    phone_number: str = Form(...),
    date_: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Парсим типы заказов из формы
    form_data = await request.form()
    order_types_data = []

    for key in form_data.keys():
        if key.startswith("type_id_"):
            row_id = key.split("_")[-1]
            type_id = form_data.get(key)
            type_amount = form_data.get(f"type_amount_{row_id}")

            if type_id and type_amount:
                order_types_data.append({
                    "type_id": int(type_id),
                    "amount": Decimal(type_amount)
                })

    # Валидация
    if not order_types_data:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один тип заказа")

    types_sum = sum(item["amount"] for item in order_types_data)
    if abs(types_sum - amount) >= Decimal("0.01"):
        raise HTTPException(status_code=400, detail=f"Сумма типов ({types_sum}) не соответствует общей сумме ({amount})")

    type_ids = [item["type_id"] for item in order_types_data]
    if len(type_ids) != len(set(type_ids)):
        raise HTTPException(status_code=400, detail="Нельзя выбрать один тип дважды")

    # Для администраторов нет ограничения по датам, для менеджеров - 14 дней
    if user.role != "admin" and abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата заказа должна быть в пределах 14 дней от сегодняшней")

    # Загружаем заказ с текущими типами
    stmt = select(Order).where(Order.id == order_id).options(
        joinedload(Order.order_order_types)
    )
    result = await session.execute(stmt)
    order = result.unique().scalars().first()

    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Обновляем основные поля
    order.phone_number = phone_number
    order.date = date_
    order.amount = amount

    # МИГРАЦИЯ: обнуляем type_id (переходим на новую схему)
    order.type_id = None

    # Удаляем старые связи с типами
    for old_type in list(order.order_order_types):
        await session.delete(old_type)

    await session.flush()

    # Создаем новые связи с типами
    for item in order_types_data:
        order_order_type = OrderOrderType(
            order_id=order.id,
            order_type_id=item["type_id"],
            amount=item["amount"]
        )
        session.add(order_order_type)

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
