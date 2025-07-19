from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, delete
from sqlalchemy.orm import joinedload, selectinload
from datetime import date
from decimal import Decimal

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
    return templates.TemplateResponse("cafe/create_shop.html", {"request": request})

@router.post("/create")
async def create_shop(name: str = Form(...), session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    await session.execute(insert(CoffeeShop).values(name=name))
    await session.commit()
    return RedirectResponse("/cafe/", status_code=302)

# 🔹 Список записей по кофейне
@router.get("/{shop_id}/records", response_class=HTMLResponse)
async def shop_records(shop_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    result = await session.execute(
        select(CoffeeShiftRecord)
        .where(CoffeeShiftRecord.shop_id == shop_id)
        .options(selectinload(CoffeeShiftRecord.barista))
        .order_by(CoffeeShiftRecord.date.desc())
    )
    records = result.scalars().all()
    return templates.TemplateResponse("cafe/records_list.html", {"request": request, "records": records, "shop_id": shop_id})

# 🔹 Создание записи кассы
@router.get("/{shop_id}/records/create", response_class=HTMLResponse)
async def create_record_page(shop_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    baristas = (await session.execute(select(User).where(User.role == UserRole.COFFEE and User.is_active))).scalars().all()
    if not baristas:
        raise HTTPException(status_code=400, detail="Нет доступных бариста для создания записи")
    return templates.TemplateResponse("cafe/create_record.html", {"request": request, "shop_id": shop_id, "baristas": baristas})

@router.post("/{shop_id}/records/create")
async def create_record(
    shop_id: int,
    date_: date = Form(...),
    total_cash: Decimal = Form(...),
    terminal: Decimal = Form(...),
    cash: Decimal = Form(...),
    expenses: Decimal = Form(...),
    barista_id: int = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_admin_user)
):
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

# 🔹 Удаление записи
@router.post("/{shop_id}/records/delete/{record_id}")
async def delete_record(shop_id: int, record_id: int, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    await session.execute(delete(CoffeeShiftRecord).where(CoffeeShiftRecord.id == record_id))
    await session.commit()
    return RedirectResponse(f"/cafe/{shop_id}/records", status_code=302)

# 🔹 Отчёт по кофейне
@router.get("/reports/{shop_id}", response_class=HTMLResponse)
async def cafe_report(shop_id: int, request: Request, session: AsyncSession = Depends(get_async_session), user: User = Depends(get_admin_user)):
    stmt = (
        select(CoffeeShiftRecord)
        .where(CoffeeShiftRecord.shop_id == shop_id)
        .options(joinedload(CoffeeShiftRecord.barista))
        .order_by(CoffeeShiftRecord.date.desc())
    )
    records = (await session.execute(stmt)).scalars().all()

    enriched = []
    for rec in records:
        base = rec.barista.default_rate or 0
        perc = rec.barista.default_percent or 0
        payout = base + (rec.total_cash * perc / 100)
        enriched.append({
            "record": rec,
            "payout": round(payout)
        })

    return templates.TemplateResponse("cafe/cafe_report.html", {
        "request": request,
        "records": enriched,
        "shop_id": shop_id
    })
