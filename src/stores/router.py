from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from src.database import get_async_session
from src.auth.dependencies import get_admin_user
from src.users.models import User, UserRole
from src.utils.csrf import generate_csrf_token, verify_csrf_token
from .models import Store, StoreShiftRecord, StoreShiftEmployee
from src.tiktok.reports.service import get_half_month_periods


async def compute_salary(
    session: AsyncSession,
    cash: Decimal,
    terminal: Decimal,
    store_ids: List[int],
    warehouse_ids: List[int],
) -> Decimal:
    ids = list(set(store_ids + warehouse_ids))
    if not ids:
        return Decimal("0.00")
    q = await session.execute(select(User).where(User.id.in_(ids)))
    users = {u.id: u for u in q.scalars().all()}
    total = Decimal("0.00")
    revenue = cash + terminal
    for uid in store_ids:
        user = users.get(uid)
        if not user:
            continue
        total += user.default_rate + revenue * user.default_percent / 100
    for uid in warehouse_ids:
        user = users.get(uid)
        if not user:
            continue
        total += user.default_rate
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse)
async def list_stores(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    result = await session.execute(select(Store))
    stores = result.scalars().all()
    if len(stores) == 1:
        store = stores[0]
        return RedirectResponse(f"/stores/{store.id}/records", status_code=302)
    return templates.TemplateResponse("stores/stores_list.html", {"request": request, "stores": stores})


@router.get("/create", response_class=HTMLResponse)
async def create_store_page(request: Request, user: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(user.id)
    return templates.TemplateResponse("stores/create_store.html", {"request": request, "csrf_token": csrf_token})


@router.post("/create")
async def create_store(
    name: str = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    session.add(Store(name=name))
    await session.commit()
    return RedirectResponse("/stores/", status_code=302)


@router.get("/{store_id}/records", response_class=HTMLResponse)
async def store_records(
    store_id: int,
    request: Request,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    today = date.today()
    if not month or not year:
        if today.day <= 7:
            target = today.replace(day=1) - timedelta(days=1)
        else:
            target = today
        month = target.month
        year = target.year

    first_range, second_range = get_half_month_periods(month, year)

    q = await session.execute(
        select(StoreShiftRecord)
        .where(
            StoreShiftRecord.store_id == store_id,
            StoreShiftRecord.date >= first_range[0],
            StoreShiftRecord.date <= second_range[1],
        )
        .options(selectinload(StoreShiftRecord.employees).selectinload(StoreShiftEmployee.user))
        .order_by(StoreShiftRecord.date)
    )
    records = q.scalars().all()

    records_by_date = {r.date: r for r in records}

    def build_range(start: date, end: date):
        data = []
        current = start
        while current <= end:
            r = records_by_date.get(current)
            if r:
                store_emps = [e for e in r.employees if not e.is_warehouse]
                wh_emps = [e for e in r.employees if e.is_warehouse]
                revenue = r.cash + r.terminal
                fixed: dict[int, Decimal] = {}
                percent: dict[int, Decimal] = {}
                for e in store_emps:
                    fixed[e.user_id] = fixed.get(e.user_id, Decimal("0.00")) + e.user.default_rate
                    percent[e.user_id] = percent.get(e.user_id, Decimal("0.00")) + revenue * e.user.default_percent / 100
                for e in wh_emps:
                    fixed[e.user_id] = fixed.get(e.user_id, Decimal("0.00")) + e.user.default_rate
                salary_by_user = {
                    uid: (fixed.get(uid, Decimal("0.00")) + percent.get(uid, Decimal("0.00"))).quantize(Decimal("0.01"))
                    for uid in set(fixed) | set(percent)
                }
                data.append(
                    {
                        "id": r.id,
                        "date": r.date,
                        "cash": r.cash,
                        "terminal": r.terminal,
                        "employees": [
                            {"id": e.user_id, "is_warehouse": e.is_warehouse} for e in r.employees
                        ],
                        "salary_by_user": salary_by_user,
                        "salary_fixed_by_user": {uid: fixed[uid].quantize(Decimal("0.01")) for uid in fixed},
                        "salary_percent_by_user": {uid: percent[uid].quantize(Decimal("0.01")) for uid in percent},
                    }
                )
            else:
                data.append(
                    {
                        "id": None,
                        "date": current,
                        "cash": Decimal("0.00"),
                        "terminal": Decimal("0.00"),
                        "employees": [],
                        "salary_by_user": {},
                        "salary_fixed_by_user": {},
                        "salary_percent_by_user": {},
                    }
                )
            current += timedelta(days=1)
        return data

    data_first = build_range(first_range[0], first_range[1])
    data_second = build_range(second_range[0], second_range[1])

    users_q = await session.execute(select(User))
    user_map = {u.id: u.name for u in users_q.scalars().all()}
    csrf_token = await generate_csrf_token(user.id)

    return templates.TemplateResponse(
        "stores/records_list.html",
        {
            "request": request,
            "store_id": store_id,
            "month": month,
            "year": year,
            "first_half": data_first,
            "second_half": data_second,
            "user_map": user_map,
            "csrf_token": csrf_token,
            "first_half_range": first_range,
            "second_half_range": second_range,
        },
    )


@router.get("/{store_id}/records/create", response_class=HTMLResponse)
async def create_record_page(
    store_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    csrf_token = await generate_csrf_token(user.id)
    store_q = await session.execute(select(User).where(User.role == UserRole.STORE_WORKER, User.is_active == True))
    store_employees = store_q.scalars().all()
    wh_q = await session.execute(select(User).where(User.role == UserRole.WAREHOUSE_WORKER, User.is_active == True))
    warehouse_employees = wh_q.scalars().all()
    return templates.TemplateResponse(
        "stores/create_record.html",
        {
            "request": request,
            "store_employees": store_employees,
            "warehouse_employees": warehouse_employees,
            "csrf_token": csrf_token,
            "store_id": store_id,
        },
    )


@router.post("/{store_id}/records/create")
async def create_record(
    store_id: int,
    date_: date = Form(...),
    cash: Decimal = Form(...),
    terminal: Decimal = Form(...),
    store_employees: List[str] = Form([]),
    warehouse_employees: List[str] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    # if not store_employees:
    #     raise HTTPException(status_code=400, detail="Select at least one store employee")
    store_employees = [int(uid) for uid in store_employees if uid.strip().isdigit()]
    warehouse_employees = [int(uid) for uid in warehouse_employees if uid.strip().isdigit()]
    salary_expenses = await compute_salary(
        session, cash, terminal, store_employees, warehouse_employees
    )
    record = StoreShiftRecord(
        store_id=store_id,
        date=date_,
        cash=cash,
        terminal=terminal,
        salary_expenses=salary_expenses,
    )
    session.add(record)
    await session.flush()
    for uid in store_employees:
        session.add(StoreShiftEmployee(shift_id=record.id, user_id=uid, is_warehouse=False))
    for uid in warehouse_employees:
        session.add(StoreShiftEmployee(shift_id=record.id, user_id=uid, is_warehouse=True))
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)


@router.post("/{store_id}/records/{record_id}/delete")
async def delete_record(
    store_id: int,
    record_id: int,
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    record = await session.get(StoreShiftRecord, record_id)
    if not record or record.store_id != store_id:
        raise HTTPException(status_code=404, detail="Record not found")
    await session.execute(
        StoreShiftEmployee.__table__.delete().where(StoreShiftEmployee.shift_id == record_id)
    )
    await session.execute(
        StoreShiftRecord.__table__.delete().where(StoreShiftRecord.id == record_id)
    )
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)


@router.get("/{store_id}/records/{record_id}/edit", response_class=HTMLResponse)
async def edit_record_page(
    store_id: int,
    record_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    record = await session.get(
        StoreShiftRecord,
        record_id,
        options=[selectinload(StoreShiftRecord.employees).selectinload(StoreShiftEmployee.user)],
    )
    if not record or record.store_id != store_id:
        raise HTTPException(status_code=404, detail="Record not found")
    csrf_token = await generate_csrf_token(user.id)
    store_q = await session.execute(select(User).where(User.role == UserRole.STORE_WORKER, User.is_active == True))
    store_employees = store_q.scalars().all()
    wh_q = await session.execute(select(User).where(User.role == UserRole.WAREHOUSE_WORKER, User.is_active == True))
    warehouse_employees = wh_q.scalars().all()
    selected_store = [e.user_id for e in record.employees if not e.is_warehouse]
    selected_warehouse = [e.user_id for e in record.employees if e.is_warehouse]
    return templates.TemplateResponse(
        "stores/edit_record.html",
        {
            "request": request,
            "record": record,
            "store_employees": store_employees,
            "warehouse_employees": warehouse_employees,
            "selected_store": selected_store,
            "selected_warehouse": selected_warehouse,
            "csrf_token": csrf_token,
            "store_id": store_id,
        },
    )


@router.post("/{store_id}/records/{record_id}/edit")
async def edit_record(
    store_id: int,
    record_id: int,
    date_: date = Form(...),
    cash: Decimal = Form(...),
    terminal: Decimal = Form(...),
    store_employees: List[str] = Form([]),
    warehouse_employees: List[str] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    record = await session.get(StoreShiftRecord, record_id)
    if not record or record.store_id != store_id:
        raise HTTPException(status_code=404, detail="Record not found")
    # if not store_employees:
    #     raise HTTPException(status_code=400, detail="Select at least one store employee")
    record.date = date_
    record.cash = cash
    record.terminal = terminal
    store_employees = [int(uid) for uid in store_employees if uid.strip().isdigit()]
    warehouse_employees = [int(uid) for uid in warehouse_employees if uid.strip().isdigit()]
    salary_expenses = await compute_salary(
        session, cash, terminal, store_employees, warehouse_employees
    )
    record.salary_expenses = salary_expenses
    await session.execute(
        StoreShiftEmployee.__table__.delete().where(StoreShiftEmployee.shift_id == record_id)
    )
    for uid in store_employees:
        session.add(StoreShiftEmployee(shift_id=record.id, user_id=uid, is_warehouse=False))
    for uid in warehouse_employees:
        session.add(StoreShiftEmployee(shift_id=record.id, user_id=uid, is_warehouse=True))
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)
