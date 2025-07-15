from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.params import Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select, insert
from datetime import date
from typing import List, Optional

from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_manager_or_admin
from src.users.models import User, UserRole
from src.shifts.models import Shift, ShiftAssignment, ShiftLocation

router = APIRouter(tags=["Shifts"])
templates = Jinja2Templates(directory="src/templates")

# 🧾 Страница создания смены
@router.get("/create", response_class=HTMLResponse)
async def create_shift_page(
    request: Request, 
    user: User = Depends(get_manager_or_admin), 
    session: AsyncSession = Depends(get_async_session),
    date: Optional[date] = Query(None)
):
    result = await session.execute(
        select(User).where(User.is_active == True, User.role == UserRole.EMPLOYEE)
    )
    users = result.scalars().all()
    return templates.TemplateResponse("shifts/create.html", {"request": request, "user": user, "users": users, "locations": list(ShiftLocation), "prefill_date": date})

# 🛠️ Обработка формы создания смены
@router.post("/create")
async def create_shift(
    date_: date = Form(...),
    location: ShiftLocation = Form(...),
    employees: List[int] = Form(...),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_manager_or_admin)
):
    if abs((date.today() - date_).days) > 14:
        raise HTTPException(status_code=400, detail="Дата смены должна быть в пределах 14 дней от сегодняшней")

    # 🧠 Ограничения
    if location == ShiftLocation.tiktok and len(employees) > 2:
        raise HTTPException(status_code=400, detail="В TikTok смене максимум 2 сотрудника")

    stmt = select(Shift).where(Shift.date == date_, Shift.location == location)
    result = await session.execute(stmt)
    if result.scalar():
        raise HTTPException(status_code=400, detail="Смена на эту дату и локацию уже существует")

    # 🏗️ Создаём саму смену
    shift = Shift(date=date_, location=location, created_by=current_user.id)
    session.add(shift)
    await session.flush()  # получаем shift.id

    # 🧩 Добавляем назначенных сотрудников
    for uid in employees:
        assignment = ShiftAssignment(
            shift_id=shift.id,
            user_id=uid,
            created_by=current_user.id
        )
        session.add(assignment)

    await session.commit()
    return RedirectResponse("/dashboard", status_code=302)

@router.get("/list", response_class=HTMLResponse)
async def shift_list_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    stmt = select(Shift).options(
        joinedload(Shift.assignments).joinedload(ShiftAssignment.user),
        joinedload(Shift.created_by_user)
    ).order_by(Shift.date.desc())

    if user.role == "manager":
        stmt = stmt.where(Shift.created_by == user.id)

    result = await session.execute(stmt)
    shifts = result.scalars().unique().all()

    return templates.TemplateResponse("shifts/list.html", {
        "request": request,
        "user": user,
        "shifts": shifts
    })

@router.get("/{shift_id}/edit", response_class=HTMLResponse)
async def edit_shift_page(
    shift_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin)
):
    shift = await session.get(Shift, shift_id, options=[
        joinedload(Shift.assignments).joinedload(ShiftAssignment.user)
    ])
    if not shift:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    result = await session.execute(
        select(User).where(User.is_active == True, User.role == UserRole.EMPLOYEE)
    )
    users = result.scalars().all()

    assigned_ids = [a.user_id for a in shift.assignments]

    return templates.TemplateResponse("shifts/edit.html", {
        "request": request,
        "shift": shift,
        "users": users,
        "assigned_ids": assigned_ids,
        "locations": list(ShiftLocation)
    })


@router.post("/{shift_id}/edit")
async def update_shift(
    shift_id: int,
    date_: date = Form(...),
    location: ShiftLocation = Form(...),
    employees: List[int] = Form(...),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_manager_or_admin)
):
    shift = await session.get(Shift, shift_id, options=[joinedload(Shift.assignments)])
    if not shift:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    if location == ShiftLocation.tiktok and len(employees) > 2:
        raise HTTPException(status_code=400, detail="В TikTok максимум 2 сотрудника")

    shift.date = date_
    shift.location = location

    # Удаляем старые назначения
    for assignment in shift.assignments:
        await session.delete(assignment)

    # Добавляем новые назначения
    for uid in employees:
        session.add(ShiftAssignment(
            shift_id=shift.id,
            user_id=uid,
            created_by=current_user.id
        ))

    await session.commit()
    return RedirectResponse("/shifts/list", status_code=302)

@router.post("/{shift_id}/delete", response_class=RedirectResponse)
async def delete_shift(
    shift_id: int,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user)
):
    # Получаем смену и связанные назначения
    shift = await session.get(Shift, shift_id, options=[joinedload(Shift.assignments)])
    if not shift:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    # Ограничение: менеджер может удалять только свои смены
    if user.role == UserRole.MANAGER and shift.created_by != user.id:
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления этой смены")

    # Удаляем назначения
    for assignment in shift.assignments:
        await session.delete(assignment)

    # Удаляем саму смену
    await session.delete(shift)
    await session.commit()

    return RedirectResponse("/shifts/list", status_code=302)

@router.get("/employees")
async def get_shift_employees(
    date: date = Query(...),
    session: AsyncSession = Depends(get_async_session),
    _: User = Depends(get_manager_or_admin),
):
    stmt = (
        select(Shift)
        .where(Shift.date == date)
        .options(joinedload(Shift.assignments).joinedload(ShiftAssignment.user))
    )
    result = await session.execute(stmt)
    shift = result.unique().scalar_one_or_none()

    if not shift:
        return {"employees": []}

    return {
        "employees": [a.user.name for a in shift.assignments]
    }
