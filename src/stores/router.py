from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select, func
from sqlalchemy.orm import selectinload
from typing import List
from datetime import date, timedelta, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

from src.database import get_async_session
from src.auth.dependencies import get_admin_user, get_cashier_or_manager_or_admin, get_manager_or_admin
from src.users.models import User, UserRole
from src.utils.csrf import generate_csrf_token, verify_csrf_token
from src.stores.models import Store, StoreShiftRecord, StoreShiftEmployee, StoreVacation
from src.tiktok.reports.service import get_half_month_periods
from src.payouts.models import Payout, RoleType, Location

from src.stores.service import aggregate_vacation_amounts, compute_salary, fetch_vacations, get_config_manager, get_payouts_for_period, get_vacations_for_period, summarize_salaries, summarize_vacations

from src.config import MANAGER_EMAIL, MANAGER_ROLE

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse)
async def list_stores(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_cashier_or_manager_or_admin),
):
    result = await session.execute(select(Store))
    stores = result.scalars().all()
    if len(stores) == 1:
        store = stores[0]
        return RedirectResponse(f"/stores/{store.id}/records", status_code=302)
    return templates.TemplateResponse("stores/stores_list.html", {"request": request, "stores": stores, "user": user})


@router.get("/create", response_class=HTMLResponse)
async def create_store_page(request: Request, user: User = Depends(get_manager_or_admin)):
    csrf_token = await generate_csrf_token(user.id)
    return templates.TemplateResponse("stores/create_store.html", {"request": request, "csrf_token": csrf_token, "user": user})


@router.post("/create")
async def create_store(
    name: str = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
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
    user: User = Depends(get_cashier_or_manager_or_admin),
):
    store = await session.get(Store, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    
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
    manager_user = await get_config_manager(session)
    manager_id = manager_user.id if manager_user else None
    records_by_date = {r.date: r for r in records}

    def build_range(start: date, end: date):
        days = []
        totals = {
            "z": Decimal("0.00"),
            "terminal": Decimal("0.00"),
            "cash_processed": Decimal("0.00"),
            "cash_on_hand": Decimal("0.00"),
        }
        salary_acc: dict[int, Decimal] = defaultdict(Decimal)
        current = start
        while current <= end:
            r = records_by_date.get(current)
            if r:
                z = r.cash or Decimal("0.00")
                terminal = r.terminal or Decimal("0.00")
                cash_processed = z - terminal
                cash_on_hand = r.cash_on_hand or Decimal("0.00")
                store_emps = [e for e in r.employees if not e.is_warehouse]
                wh_emps = [e for e in r.employees if e.is_warehouse]
                for e in store_emps + wh_emps:
                    salary_acc[e.user_id] = salary_acc.get(e.user_id, Decimal("0.00")) + e.user.default_rate
                days.append(
                    {
                        "id": r.id,
                        "date": r.date,
                        "cash": z,
                        "terminal": terminal,
                        "cash_processed": cash_processed,
                        "cash_on_hand": cash_on_hand,
                        "changed_price": r.changed_price,
                        "discount": r.discount,
                        "promotion": r.promotion,
                        "to_store": r.to_store,
                        "refund": r.refund,
                        "service": r.service,
                        "receipt": r.receipt,
                        "employees": [
                            {"id": e.user_id, "is_warehouse": e.is_warehouse}
                            for e in r.employees
                            if e.user_id != manager_id
                        ],
                    }
                )
                totals["z"] += z
                totals["terminal"] += terminal
                totals["cash_processed"] += cash_processed
                totals["cash_on_hand"] += cash_on_hand
            else:
                days.append(
                    {
                        "id": None,
                        "date": current,
                        "cash": Decimal("0.00"),
                        "terminal": Decimal("0.00"),
                        "cash_processed": Decimal("0.00"),
                        "cash_on_hand": Decimal("0.00"),
                        "changed_price": Decimal("0.00"),
                        "discount": Decimal("0.00"),
                        "promotion": Decimal("0.00"),
                        "to_store": Decimal("0.00"),
                        "refund": Decimal("0.00"),
                        "service": Decimal("0.00"),
                        "receipt": Decimal("0.00"),
                        "employees": [],
                    }
                )
            current += timedelta(days=1)
        return days, totals, salary_acc

    days_first, totals_first, salary_acc_first = build_range(first_range[0], first_range[1])
    days_second, totals_second, salary_acc_second = build_range(second_range[0], second_range[1])

    payouts_first = await get_payouts_for_period(
        session, first_range[0], first_range[1], user
    )
    payouts_second = await get_payouts_for_period(
        session, second_range[0], second_range[1], user
    )

    vac_first_records = await fetch_vacations(
        session, store_id, first_range[0], first_range[1]
    )
    vac_second_records = await fetch_vacations(
        session, store_id, second_range[0], second_range[1]
    )

    vac_first_amounts = aggregate_vacation_amounts(
        vac_first_records, first_range[0], first_range[1]
    )
    vac_second_amounts = aggregate_vacation_amounts(
        vac_second_records, second_range[0], second_range[1]
    )

    for uid, amt in vac_first_amounts.items():
        salary_acc_first[uid] += amt
    for uid, amt in vac_second_amounts.items():
        salary_acc_second[uid] += amt

    first_half = {
        "days": days_first,
        "totals": totals_first,
        "salaries": summarize_salaries(salary_acc_first, payouts_first),
        "vacations": [
            {
                "id": v.id,
                "user_id": v.user_id,
                "start_date": v.start_date,
                "end_date": v.end_date,
                "amount": Decimal(v.amount).quantize(Decimal("0.01")),
            }
            for v in vac_first_records
        ],
    }
    second_half = {
        "days": days_second,
        "totals": totals_second,
        "salaries": summarize_salaries(salary_acc_second, payouts_second),
        "vacations": [
            {
                "id": v.id,
                "user_id": v.user_id,
                "start_date": v.start_date,
                "end_date": v.end_date,
                "amount": Decimal(v.amount).quantize(Decimal("0.01")),
            }
            for v in vac_second_records
        ],
    }

    users_q = await session.execute(select(User))
    user_map = {u.id: u.name for u in users_q.scalars().all()}
    csrf_token = await generate_csrf_token(user.id)

    return templates.TemplateResponse(
        "stores/records_list.html",
        {
            "request": request,
            "store_id": store_id,
            "store_name": store.name,
            "month": month,
            "year": year,
            "first_half": first_half,
            "second_half": second_half,
            "user_map": user_map,
            "csrf_token": csrf_token,
            "first_half_range": first_range,
            "second_half_range": second_range,
            "user": user,
        },
    )


@router.post("/{store_id}/pay")
async def make_payout(
    store_id: int,
    user_id: int = Form(...),
    date: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    payer_user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(payer_user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role_type = RoleType(user.role.value)
    payout = Payout(
        user_id=user_id,
        date=date,
        location=Location.Store,
        role_type=role_type,
        amount=amount,
        paid_at=datetime.utcnow(),
        is_manual=True,
    )
    session.add(payout)
    await session.commit()
    return RedirectResponse(
        f"/stores/{store_id}/records?month={date.month}&year={date.year}", status_code=302
    )


@router.get("/{store_id}/records/create", response_class=HTMLResponse)
async def create_record_page(
    store_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_cashier_or_manager_or_admin),
):
    csrf_token = await generate_csrf_token(user.id)
    store_q = await session.execute(select(User).where(User.role == UserRole.STORE_WORKER, User.is_active == True))
    store_employees = store_q.scalars().all()
    wh_q = await session.execute(select(User).where(User.role == UserRole.WAREHOUSE_WORKER, User.is_active == True))
    warehouse_employees = wh_q.scalars().all()
    vac_q = await session.execute(
        select(StoreVacation.user_id, StoreVacation.start_date, StoreVacation.end_date).where(
            StoreVacation.store_id == store_id
        )
    )
    vacations = [
        {
            "user_id": uid,
            "start": sd.isoformat(),
            "end": ed.isoformat(),
        }
        for uid, sd, ed in vac_q.all()
    ]
    return templates.TemplateResponse(
        "stores/create_record.html",
        {
            "request": request,
            "store_employees": store_employees,
            "warehouse_employees": warehouse_employees,
            "vacations": vacations,
            "csrf_token": csrf_token,
            "store_id": store_id,
            "user": user,
        },
    )


@router.post("/{store_id}/records/create")
async def create_record(
    store_id: int,
    request: Request,
    date_: date = Form(...),
    cash: Decimal = Form(...),
    cash_on_hand: Decimal = Form(...),
    terminal: Decimal = Form(...),
    changed_price: Decimal = Form(0),
    discount: Decimal = Form(0),
    promotion: Decimal = Form(0),
    to_store: Decimal = Form(0),
    refund: Decimal = Form(0),
    service: Decimal = Form(0),
    receipt: Decimal = Form(0),
    cash_comment: str = Form(""),
    cash_on_hand_comment: str = Form(""),
    terminal_comment: str = Form(""),
    changed_price_comment: str = Form(""),
    discount_comment: str = Form(""),
    promotion_comment: str = Form(""),
    to_store_comment: str = Form(""),
    refund_comment: str = Form(""),
    service_comment: str = Form(""),
    receipt_comment: str = Form(""),
    store_employees: List[str] = Form([]),
    warehouse_employees: List[str] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_cashier_or_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if not store_employees:
        raise HTTPException(status_code=400, detail="Нужно выбрать хотя бы одного сотрудника магазина")
    stmt = select(StoreShiftRecord).where(StoreShiftRecord.date == date_, StoreShiftRecord.store_id == store_id)
    result = await session.execute(stmt)
    if result.scalar():
        raise HTTPException(status_code=400, detail="Смена на эту дату и локацию уже существует")

    store_employees = [int(uid) for uid in store_employees if uid.strip().isdigit()]
    warehouse_employees = [int(uid) for uid in warehouse_employees if uid.strip().isdigit()]
    manager_user = await get_config_manager(session)
    if manager_user and manager_user.id not in store_employees:
        store_employees.append(manager_user.id)
    
    user_ids = store_employees + warehouse_employees
    vac_stmt = select(StoreVacation).where(
        StoreVacation.store_id == store_id,
        StoreVacation.user_id.in_(user_ids),
        StoreVacation.start_date <= date_,
        StoreVacation.end_date >= date_,
    )
    if (await session.execute(vac_stmt)).first():
        raise HTTPException(status_code=400, detail="Сотрудник в отпуске")

    form = await request.form()
    assignments = []
    for uid in store_employees + warehouse_employees:
        assignments.append(
            (
                uid,
                form.get(f"start_time_{uid}"),
                form.get(f"end_time_{uid}"),
            )
        )

    salary_expenses = await compute_salary(session, assignments)

    comments: dict[str, str] = {}
    if cash_comment:
        comments["cash"] = cash_comment
    if cash_on_hand_comment:
        comments["cash_on_hand"] = cash_on_hand_comment
    if terminal_comment:
        comments["terminal"] = terminal_comment
    if changed_price_comment:
        comments["changed_price"] = changed_price_comment
    if discount_comment:
        comments["discount"] = discount_comment
    if promotion_comment:
        comments["promotion"] = promotion_comment
    if to_store_comment:
        comments["to_store"] = to_store_comment
    if refund_comment:
        comments["refund"] = refund_comment
    if service_comment:
        comments["service"] = service_comment
    if receipt_comment:
        comments["receipt"] = receipt_comment
    record = StoreShiftRecord(
        store_id=store_id,
        date=date_,
        cash=cash,
        cash_on_hand=cash_on_hand,
        terminal=terminal,
        changed_price=changed_price,
        discount=discount,
        promotion=promotion,
        to_store=to_store,
        refund=refund,
        service=service,
        receipt=receipt,
        salary_expenses=salary_expenses,
        comments=comments,
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
        raise HTTPException(status_code=404, detail="Смена не найдена")
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
    user: User = Depends(get_manager_or_admin),
):
    record = await session.get(
        StoreShiftRecord,
        record_id,
        options=[selectinload(StoreShiftRecord.employees).selectinload(StoreShiftEmployee.user)],
    )
    if not record or record.store_id != store_id:
        raise HTTPException(status_code=404, detail="Смена не найдена")
    csrf_token = await generate_csrf_token(user.id)
    
    store_q = await session.execute(select(User).where(User.role == UserRole.STORE_WORKER, User.is_active == True))
    store_employees = store_q.scalars().all()
    manager_user = await get_config_manager(session)
    if manager_user and manager_user not in store_employees:
        store_employees.append(manager_user)
    wh_q = await session.execute(select(User).where(User.role == UserRole.WAREHOUSE_WORKER, User.is_active == True))
    warehouse_employees = wh_q.scalars().all()
    selected_store = [e.user_id for e in record.employees if not e.is_warehouse]
    selected_warehouse = [e.user_id for e in record.employees if e.is_warehouse]
    vac_q = await session.execute(
        select(StoreVacation.user_id).where(
            StoreVacation.store_id == store_id,
            StoreVacation.start_date <= record.date,
            StoreVacation.end_date >= record.date,
        )
    )
    vacation_users = [uid for uid, in vac_q.all()]

    return templates.TemplateResponse(
        "stores/edit_record.html",
        {
            "request": request,
            "record": record,
            "store_employees": store_employees,
            "warehouse_employees": warehouse_employees,
            "selected_store": selected_store,
            "selected_warehouse": selected_warehouse,
            "vacation_users": vacation_users,
            "csrf_token": csrf_token,
            "store_id": store_id,
            "user": user,
        },
    )


@router.post("/{store_id}/records/{record_id}/edit")
async def edit_record(
    store_id: int,
    record_id: int,
    request: Request,
    date_: date = Form(...),
    cash: Decimal = Form(...),
    cash_on_hand: Decimal = Form(...),
    terminal: Decimal = Form(...),
    changed_price: Decimal = Form(0),
    discount: Decimal = Form(0),
    promotion: Decimal = Form(0),
    to_store: Decimal = Form(0),
    refund: Decimal = Form(0),
    service: Decimal = Form(0),
    receipt: Decimal = Form(0),
    cash_comment: str = Form(""),
    cash_on_hand_comment: str = Form(""),
    terminal_comment: str = Form(""),
    changed_price_comment: str = Form(""),
    discount_comment: str = Form(""),
    promotion_comment: str = Form(""),
    to_store_comment: str = Form(""),
    refund_comment: str = Form(""),
    service_comment: str = Form(""),
    receipt_comment: str = Form(""),
    store_employees: List[str] = Form([]),
    warehouse_employees: List[str] = Form([]),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    record = await session.get(StoreShiftRecord, record_id)
    if not record or record.store_id != store_id:
        raise HTTPException(status_code=404, detail="Смена не найдена")
    if not store_employees:
        raise HTTPException(status_code=400, detail="Нужно выбрать хотя бы одного сотрудника магазина")
    record.date = date_
    record.cash = cash
    record.terminal = terminal
    record.cash_on_hand = cash_on_hand
    record.changed_price = changed_price
    record.discount = discount
    record.promotion = promotion
    record.to_store = to_store
    record.refund = refund
    record.service = service
    record.receipt = receipt

    comments = dict(record.comments or {})
    def set_comment(field: str, value: str):
        if value:
            comments[field] = value
        else:
            comments.pop(field, None)

    set_comment("cash", cash_comment)
    set_comment("cash_on_hand", cash_on_hand_comment)
    set_comment("terminal", terminal_comment)
    set_comment("changed_price", changed_price_comment)
    set_comment("discount", discount_comment)
    set_comment("promotion", promotion_comment)
    set_comment("to_store", to_store_comment)
    set_comment("refund", refund_comment)
    set_comment("service", service_comment)
    set_comment("receipt", receipt_comment)
    record.comments = comments

    store_employees = [int(uid) for uid in store_employees if uid.strip().isdigit()]
    warehouse_employees = [int(uid) for uid in warehouse_employees if uid.strip().isdigit()]
    manager_user = await get_config_manager(session)
    if manager_user and manager_user.id not in store_employees:
        store_employees.append(manager_user.id)

    user_ids = store_employees + warehouse_employees
    vac_stmt = select(StoreVacation).where(
        StoreVacation.store_id == store_id,
        StoreVacation.user_id.in_(user_ids),
        StoreVacation.start_date <= date_,
        StoreVacation.end_date >= date_,
    )
    if (await session.execute(vac_stmt)).first():
        raise HTTPException(status_code=400, detail="Сотрудник в отпуске")
    
    form = await request.form()
    assignments = []
    for uid in store_employees + warehouse_employees:
        assignments.append(
            (
                uid,
                form.get(f"start_time_{uid}"),
                form.get(f"end_time_{uid}"),
            )
        )
    salary_expenses = await compute_salary(session, assignments)
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


@router.get("/{store_id}/vacations/create", response_class=HTMLResponse)
async def create_vacation_page(
    store_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    csrf_token = await generate_csrf_token(user.id)
    q = await session.execute(
        select(User).where(User.is_active == True, User.can_take_vacation == True)
    )
    employees = q.scalars().all()
    return templates.TemplateResponse(
        "stores/create_vacation.html",
        {
            "request": request,
            "employees": employees,
            "csrf_token": csrf_token,
            "store_id": store_id,
            "user": user,
        },
    )


@router.post("/{store_id}/vacations/create")
async def create_vacation(
    store_id: int,
    user_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    u = await session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if not u.can_take_vacation:
        raise HTTPException(status_code=400, detail="Сотрудник не оформлен для отпуска")
    days = (end_date - start_date).days + 1
    if days <= 0 or days > 31:
        raise HTTPException(status_code=400, detail="Invalid date range")
    shift_stmt = (
        select(StoreShiftEmployee)
        .join(StoreShiftRecord)
        .where(
            StoreShiftRecord.store_id == store_id,
            StoreShiftRecord.date >= start_date,
            StoreShiftRecord.date <= end_date,
            StoreShiftEmployee.user_id == user_id,
        )
    )
    if (await session.execute(shift_stmt)).first():
        raise HTTPException(
            status_code=400, detail="Сотрудник уже назначен на смену в эти даты"
        )
    amount_calc = Decimal(u.default_rate) * days
    vacation = StoreVacation(
        store_id=store_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        amount=amount_calc,
    )
    session.add(vacation)
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)


@router.get("/{store_id}/vacations/{vacation_id}/edit", response_class=HTMLResponse)
async def edit_vacation_page(
    store_id: int,
    vacation_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    vacation = await session.get(StoreVacation, vacation_id)
    if not vacation or vacation.store_id != store_id:
        raise HTTPException(status_code=404, detail="Vacation not found")
    csrf_token = await generate_csrf_token(user.id)
    q = await session.execute(
        select(User).where(
            User.is_active == True,
            or_(User.can_take_vacation == True, User.id == vacation.user_id),
        )
    )
    employees = q.scalars().all()
    return templates.TemplateResponse(
        "stores/edit_vacation.html",
        {
            "request": request,
            "vacation": vacation,
            "employees": employees,
            "csrf_token": csrf_token,
            "store_id": store_id,
            "user": user,
        },
    )


@router.post("/{store_id}/vacations/{vacation_id}/edit")
async def edit_vacation(
    store_id: int,
    vacation_id: int,
    user_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    amount: Decimal = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_manager_or_admin),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    vacation = await session.get(StoreVacation, vacation_id)
    if not vacation or vacation.store_id != store_id:
        raise HTTPException(status_code=404, detail="Vacation not found")
    u = await session.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if not u.can_take_vacation:
        raise HTTPException(status_code=400, detail="Сотрудник не оформлен для отпуска")
    days = (end_date - start_date).days + 1
    if days <= 0 or days > 31:
        raise HTTPException(status_code=400, detail="Invalid date range")
    shift_stmt = (
        select(StoreShiftEmployee)
        .join(StoreShiftRecord)
        .where(
            StoreShiftRecord.store_id == store_id,
            StoreShiftRecord.date >= start_date,
            StoreShiftRecord.date <= end_date,
            StoreShiftEmployee.user_id == user_id,
        )
    )
    if (await session.execute(shift_stmt)).first():
        raise HTTPException(
            status_code=400, detail="Сотрудник уже назначен на смену в эти даты"
        )
    amount_calc = Decimal(u.default_rate) * days
    vacation.user_id = user_id
    vacation.start_date = start_date
    vacation.end_date = end_date
    vacation.amount = amount_calc
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)


@router.post("/{store_id}/vacations/{vacation_id}/delete")
async def delete_vacation(
    store_id: int,
    vacation_id: int,
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    vacation = await session.get(StoreVacation, vacation_id)
    if not vacation or vacation.store_id != store_id:
        raise HTTPException(status_code=404, detail="Vacation not found")
    await session.delete(vacation)
    await session.commit()
    return RedirectResponse(f"/stores/{store_id}/records", status_code=302)
