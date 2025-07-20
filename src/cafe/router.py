from collections import defaultdict
from fastapi import APIRouter, Depends, Form, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete
from sqlalchemy.orm import joinedload, selectinload
from datetime import date, timedelta
from decimal import Decimal
from calendar import monthrange
from src.utils.csrf import generate_csrf_token, verify_csrf_token

from src.database import get_async_session
from src.auth.dependencies import get_admin_user
from src.users.models import User, UserRole
from src.cafe.models import CoffeeShop, CoffeeShiftRecord

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

# 🔹 Список кофеен
@router.get("/", response_class=HTMLResponse)
async def list_shops(request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    result = await session.execute(select(CoffeeShop))
    shops = result.scalars().all()
    return templates.TemplateResponse("cafe/shops_list.html", {"request": request, "shops": shops})

# 🔹 Создание кофейни
@router.get("/create", response_class=HTMLResponse)
async def create_shop_page(request: Request, user: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(user.id)
    return templates.TemplateResponse("cafe/create_shop.html", {"request": request, "csrf_token": csrf_token})

@router.post("/create")
async def create_shop(
    name: str = Form(...), 
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session), 
    user: User = Depends(get_admin_user)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    await session.execute(insert(CoffeeShop).values(name=name))
    await session.commit()
    return RedirectResponse("/cafe/", status_code=302)

from fastapi import Query
from calendar import monthrange

@router.get("/{shop_id}/records", response_class=HTMLResponse)
async def shop_records(
    shop_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
    month: int = Query(date.today().month),
    year: int = Query(date.today().year),
    sort_by: str = Query("desc")
):
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    stmt = (
        select(CoffeeShiftRecord)
        .where(CoffeeShiftRecord.shop_id == shop_id)
        .where(CoffeeShiftRecord.date.between(first_day, last_day))
        .options(selectinload(CoffeeShiftRecord.barista))
    )

    if sort_by == "asc":
        stmt = stmt.order_by(CoffeeShiftRecord.date.asc())
    else:
        stmt = stmt.order_by(CoffeeShiftRecord.date.desc())

    result = await session.execute(stmt)
    records = result.scalars().all()

    return templates.TemplateResponse("cafe/records_list.html", {
        "request": request,
        "records": records,
        "shop_id": shop_id,
        "month": month,
        "year": year,
        "sort_by": sort_by,
        "user": user
    })

@router.get("/{shop_id}/edit", response_class=HTMLResponse)
async def edit_shop_page(shop_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(user.id)

    shop = await session.get(CoffeeShop, shop_id)
    return templates.TemplateResponse("cafe/edit_shop.html", {"request": request, "shop": shop, "csrf_token": csrf_token})

@router.post("/{shop_id}/edit")
async def edit_shop(
    shop_id: int, 
    name: str = Form(...), 
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session), 
    user: User = Depends(get_admin_user)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    shop = await session.get(CoffeeShop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Кофейня не найдена")
    shop.name = name
    await session.commit()
    return RedirectResponse("/cafe/", status_code=302)

# 🔹 Создание записи кассы
@router.get("/{shop_id}/records/create", response_class=HTMLResponse)
async def create_record_page(shop_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(user.id)

    baristas = (await session.execute(select(User).where(User.role == UserRole.COFFEE and User.is_active))).scalars().all()
    if not baristas:
        raise HTTPException(status_code=400, detail="Нет доступных бариста для создания записи")
    return templates.TemplateResponse("cafe/create_record.html", {"request": request, "shop_id": shop_id, "baristas": baristas, "csrf_token": csrf_token})

@router.post("/{shop_id}/records/create")
async def create_record(
    shop_id: int,
    date_: date = Form(...),
    total_cash: Decimal = Form(...),
    terminal: Decimal = Form(...),
    cash: Decimal = Form(...),
    expenses: Decimal = Form(...),
    barista_id: int = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    record = (await session.execute(select(CoffeeShiftRecord).where(CoffeeShiftRecord.date == date_ and CoffeeShiftRecord.shop_id == shop_id))).scalars().all()
    if record:
        return HTTPException(status_code=400, detail="Запись существует")

    barista = await session.get(User, barista_id)
    if not barista or barista.role != UserRole.COFFEE:
        raise HTTPException(status_code=400, detail="Неверный бариста")

    stmt = insert(CoffeeShiftRecord).values(
        date=date_,
        total_cash=total_cash,
        terminal=terminal,
        cash=cash,
        expenses=expenses,
        shop_id=shop_id,
        barista_id=barista_id
    )
    await session.execute(stmt)
    await session.commit()
    return RedirectResponse(f"/cafe/{shop_id}/records", status_code=302)

@router.get("/{shop_id}/records/edit/{record_id}", response_class=HTMLResponse)
async def edit_record_page(shop_id: int, record_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    csrf_token = await generate_csrf_token(user.id)
    
    record = await session.get(CoffeeShiftRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    baristas = (await session.execute(select(User).where(User.role == UserRole.COFFEE and User.is_active))).scalars().all()
    return templates.TemplateResponse("cafe/edit_record.html", {"request": request, "record": record, "baristas": baristas, "shop_id": shop_id, "csrf_token": csrf_token})

@router.post("/{shop_id}/records/edit/{record_id}")
async def edit_record(
    shop_id: int, 
    record_id: int, 
    date_: date = Form(...), 
    total_cash: Decimal = Form(...), 
    terminal: Decimal = Form(...), 
    cash: Decimal = Form(...), 
    expenses: Decimal = Form(...), 
    barista_id: int = Form(...),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session), 
    user: User = Depends(get_admin_user)
):
    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    record = await session.get(CoffeeShiftRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    record.date = date_
    record.total_cash = total_cash
    record.terminal = terminal
    record.cash = cash
    record.expenses = expenses
    record.barista_id = barista_id
    await session.commit()
    return RedirectResponse(f"/cafe/{shop_id}/records", status_code=302)

# 🔹 Удаление записи
@router.post("/{shop_id}/records/delete/{record_id}")
async def delete_record(shop_id: int, record_id: int, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    await session.execute(delete(CoffeeShiftRecord).where(CoffeeShiftRecord.id == record_id))
    await session.commit()
    return RedirectResponse(f"/cafe/{shop_id}/records", status_code=302)

@router.get("/{shop_id}/reports", response_class=HTMLResponse)
async def cafe_report(
    shop_id: int,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user),
    month: int = Query(date.today().month),
    year: int = Query(date.today().year)
):
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    mid_day = date(year, month, 15)

    stmt = (
        select(CoffeeShiftRecord)
        .where(CoffeeShiftRecord.shop_id == shop_id)
        .where(CoffeeShiftRecord.date.between(first_day, last_day))
        .options(joinedload(CoffeeShiftRecord.barista))
    )
    all_records = (await session.execute(stmt)).scalars().all()
    records_by_date = {r.date: r for r in all_records}

    def generate_enriched_range(start: date, end: date):
        result = []
        current = start
        while current <= end:
            rec = records_by_date.get(current)
            if rec:
                base = rec.barista.default_rate or 0
                perc = rec.barista.default_percent or 0
                payout = float(base) + float(rec.total_cash) * float(perc) / 100
                result.append({
                    "record": rec,
                    "payout": round(payout),
                    "percent": perc
                })
            else:
                result.append({
                    "record": None,
                    "payout": 0,
                    "percent": 0,
                    "date": current
                })
            current += timedelta(days=1)
        return result

    def get_summary(enriched):
        total_cash = 0
        total_terminal = 0
        total_cash_only = 0
        total_expenses = 0
        total_salary = 0
        users = defaultdict(lambda: {"name": "", "percent": 0, "total": 0})

        for r in enriched:
            rec = r.get("record")
            if rec:
                total_cash += float(rec.total_cash)
                total_terminal += float(rec.terminal)
                total_cash_only += float(rec.cash)
                total_expenses += float(rec.expenses)
                total_salary += r["payout"]
                u = rec.barista
                users[u.id]["name"] = u.name
                users[u.id]["percent"] = r["percent"]
                users[u.id]["total"] += r["payout"]

        return {
            "records": enriched,
            "total_cash": round(total_cash),
            "total_terminal": round(total_terminal),
            "total_cash_only": round(total_cash_only),
            "total_expenses": round(total_expenses),
            "total_salary": round(total_salary),
            "net_profit": round(total_cash - total_expenses - total_salary),
            "user_summary": users
        }

    enriched_1_15 = generate_enriched_range(first_day, mid_day)
    enriched_16_31 = generate_enriched_range(mid_day.replace(day=16), last_day)

    summary_1_15 = get_summary(enriched_1_15)
    summary_16_31 = get_summary(enriched_16_31)

    return templates.TemplateResponse("cafe/cafe_report.html", {
        "request": request,
        "shop_id": shop_id,
        "month": month,
        "year": year,
        "first_half": summary_1_15["records"],
        "second_half": summary_16_31["records"],
        "first_start": first_day,
        "first_end": mid_day,
        "second_start": mid_day.replace(day=16),
        "second_end": last_day,
        "user_summary": {
            "1–15": summary_1_15["user_summary"],
            "16–конец": summary_16_31["user_summary"]
        },
        "user": user,
    })
