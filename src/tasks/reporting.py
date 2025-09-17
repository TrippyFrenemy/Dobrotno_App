from __future__ import annotations

import asyncio
import html
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Iterable

import httpx
from celery import shared_task
from sqlalchemy import select, text as sa_text
from sqlalchemy.orm import selectinload

from src.config import TG_BOT_TOKEN, TG_CHAT_ID
from src.database import async_session_maker
from src.tiktok.reports.service import (
    get_monthly_report,
    get_payouts_for_period as get_tiktok_payouts,
    summarize_period,
)
from src.users.models import User, UserRole
from src.stores.models import Store, StoreShiftRecord, StoreShiftEmployee
from src.stores.service import (
    aggregate_vacation_amounts,
    fetch_vacations,
    get_config_manager,
    get_payouts_for_period as get_store_payouts,
    summarize_salaries,
)

SYSTEM_USER = SimpleNamespace(role=UserRole.ADMIN)

# -------- formatting helpers --------

def _fmt_decimal(value: Decimal | int | float | None) -> str:
    if value is None:
        value = Decimal("0")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{float(q):,.0f}"

def _esc(s: str) -> str:
    # для parse_mode=HTML
    return html.escape(s, quote=False)

def _mono_line(parts: list[tuple[str, str]]) -> str:
    # parts: [("Z", "123.45"), ("Терминал", "45.00")]
    return "<code>" + " | ".join(f"{_esc(k)}: {v}" for k, v in parts) + "</code>"

def _collapse_no_data_days(days_flags: dict[date, bool]) -> str:
    missing_ranges: list[tuple[date, date]] = []
    start = None
    prev = None
    for d in sorted(days_flags.keys()):
        if not days_flags[d]:
            if start is None:
                start = d
            prev = d
        else:
            if start is not None:
                missing_ranges.append((start, prev))
                start, prev = None, None
    if start is not None:
        missing_ranges.append((start, prev))

    def fmt_range(a: date, b: date) -> str:
        return a.strftime("%d.%m") if a == b else f"{a.strftime('%d.%m')}–{b.strftime('%d.%m')}"
    return ", ".join(fmt_range(a, b) for a, b in missing_ranges) or "—"

# -------- period selection --------

def _build_period_for_today(today: date) -> tuple[date, date] | None:
    if today.day >= 15:
        return today.replace(day=1), today.replace(day=15)
    if 1 <= today.day <= 14:
        first_of_month = today.replace(day=1)
        previous_day = first_of_month - timedelta(days=1)
        return previous_day.replace(day=16), previous_day
    return None

# -------- db fetch --------

async def _fetch_user_map() -> dict[int, str]:
    async with async_session_maker() as session:
        async with session.begin():
            # жёстко — запросы только на чтение
            await session.execute(sa_text("SET TRANSACTION READ ONLY"))
            result = await session.execute(select(User.id, User.name))
            return {user_id: name for user_id, name in result.all()}

# -------- reports --------

async def _collect_tiktok_report(start: date, end: date, user_map: dict[int, str]) -> tuple[str, str]:
    """
    Возвращает:
      - summary_text: компактный HTML-текст для чата
      - details_text: подробный текст для файла
    """
    async with async_session_maker() as session:
        async with session.begin():
            await session.execute(sa_text("SET TRANSACTION READ ONLY"))
            days = await get_monthly_report(session, start, end, current_user=SYSTEM_USER)
            payouts = await get_tiktok_payouts(session, start, end, current_user=SYSTEM_USER)

    summary = summarize_period(days, payouts)

    # --- summary (короткая сводка)
    lines: list[str] = [
        f"<b>TikTok — отчёт</b> {_esc(start.strftime('%d.%m.%Y'))}–{_esc(end.strftime('%d.%m.%Y'))}"
    ]
    totals = summary["totals"]
    lines.append(
        _mono_line([
            ("Заказы", _fmt_decimal(totals['orders'])),
            ("Возвраты", _fmt_decimal(totals['returns'])),
            ("Касса", _fmt_decimal(totals['cashbox'])),
        ])
    )
    if summary["salaries"]:
        lines.append("<b>Зарплаты</b>")
        total_paid = Decimal("0")
        total_accrued = Decimal("0")
        for item in summary["salaries"]:
            name = _esc(user_map.get(item["user_id"], f"ID {item['user_id']}"))
            fixed = _fmt_decimal(item["fixed"])
            percent = _fmt_decimal(item["percent"])
            total = _fmt_decimal(item["total"])
            paid = _fmt_decimal(item["paid"])
            remaining = _fmt_decimal(item["remaining"])
            total_paid += Decimal(item["paid"])
            total_accrued += Decimal(item["total"])
            lines.append(
                f"  {name}: начислено {total} (фикс {fixed}, % {percent}), выплачено {paid}, остаток {remaining}"
            )
        # (1) Итого ЗП за весь период
        lines.append(_esc(f"Итого ЗП за весь период со всех сотрудников: {_fmt_decimal(total_accrued)}"))
        # (2) Выплачено за период всего
        lines.append(_esc(f"Выплачено за период всего: {_fmt_decimal(total_paid)}"))
        # после (2): сколько осталось выплатить
        remaining_total = total_accrued - total_paid
        lines.append(_esc(f"Осталось выплатить за период всего: {_fmt_decimal(remaining_total)}"))

    summary_text = "\n".join(lines)

    # --- details (полная детализация по дням)
    det: list[str] = [
        f"TikTok — детальный отчёт за период {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}",
        "По дням:",
    ]
    for day in summary["days"]:
        det.append(
            f"  {day['date'].strftime('%d.%m')}: заказы {_fmt_decimal(day['orders'])}, "
            f"возвраты {_fmt_decimal(day['returns'])}, касса {_fmt_decimal(day['cashbox'])}"
        )
        if day["salary_by_user"]:
            salary_details = []
            for uid, amount in day["salary_by_user"].items():
                name = user_map.get(uid, f"ID {uid}")
                salary_details.append(f"{name}: {_fmt_decimal(amount)}")
            det.append("    Начисления: " + ", ".join(salary_details))
        if day["employees"]:
            employee_details = []
            for emp in day["employees"]:
                name = user_map.get(emp["user_id"], f"ID {emp['user_id']}")
                st = emp.get("start_time").strftime("%H:%M") if emp.get("start_time") else "—"
                en = emp.get("end_time").strftime("%H:%M") if emp.get("end_time") else "—"
                # ставка не выводим в summary-части; в details — оставим:
                sal = emp.get("salary")
                salary_part = f", ставка {_fmt_decimal(sal)}" if sal is not None else ""
                employee_details.append(f"{name} {st}–{en}{salary_part}")
            det.append("    Сотрудники: " + ", ".join(employee_details))

    # Итоги по зарплатам в деталях (агрегат по всему периоду)
    if summary["salaries"]:
        total_paid = sum(Decimal(x["paid"]) for x in summary["salaries"])
        total_accrued = sum(Decimal(x["total"]) for x in summary["salaries"])
        remaining_total = total_accrued - total_paid
        det.append(f"Итого ЗП за весь период со всех сотрудников: {_fmt_decimal(total_accrued)}")
        det.append(f"Выплачено за период всего: {_fmt_decimal(total_paid)}")
        det.append(f"Осталось выплатить за период всего: {_fmt_decimal(remaining_total)}")


    details_text = "\n".join(det)
    return summary_text, details_text

async def _collect_store_reports(start: date, end: date, user_map: dict[int, str]) -> tuple[list[str], str]:
    """
    Возвращает:
      - summaries: список компактных HTML-текстов по магазинам (для чата)
      - details_text: общий подробный текст по всем магазинам (для файла)
    """
    summaries: list[str] = []
    details_all: list[str] = []

    async with async_session_maker() as session:
        async with session.begin():
            await session.execute(sa_text("SET TRANSACTION READ ONLY"))
            stores_result = await session.execute(select(Store))
            stores = stores_result.scalars().all()
            manager = await get_config_manager(session)
            manager_id = manager.id if manager else None
            payouts_map = await get_store_payouts(session, start, end, SYSTEM_USER)

            for store in stores:
                stmt = (
                    select(StoreShiftRecord)
                    .where(
                        StoreShiftRecord.store_id == store.id,
                        StoreShiftRecord.date >= start,
                        StoreShiftRecord.date <= end,
                    )
                    .options(
                        selectinload(StoreShiftRecord.employees).selectinload(
                            StoreShiftEmployee.user
                        )
                    )
                    .order_by(StoreShiftRecord.date)
                )
                records = (await session.execute(stmt)).scalars().all()
                records_by_date = {record.date: record for record in records}

                totals = defaultdict(lambda: Decimal("0"))
                salary_acc: dict[int, Decimal] = defaultdict(Decimal)
                days_lines: list[str] = []
                days_presence: dict[date, bool] = {}

                current = start
                while current <= end:
                    record = records_by_date.get(current)
                    if record:
                        cash = Decimal(record.cash or 0)
                        terminal = Decimal(record.terminal or 0)
                        cash_processed = cash - terminal
                        cash_on_hand = Decimal(record.cash_on_hand or 0)
                        changed_price = Decimal(record.changed_price or 0)
                        discount = Decimal(record.discount or 0)
                        promotion = Decimal(record.promotion or 0)
                        to_store = Decimal(record.to_store or 0)
                        refund = Decimal(record.refund or 0)
                        service = Decimal(record.service or 0)
                        receipt = Decimal(record.receipt or 0)
                        expenses = Decimal(record.expenses or 0)
                        expense_total = Decimal(record.expense_total or 0)
                        cash_total = Decimal(record.cash_total or 0)

                        store_emps = [e for e in record.employees if not e.is_warehouse]
                        wh_emps = [e for e in record.employees if e.is_warehouse]
                        # аккумулируем начисления (ставки/дефолтные)
                        for employee in store_emps + wh_emps:
                            salary_value = (
                                Decimal(employee.salary)
                                if employee.salary is not None
                                else Decimal(employee.user.default_rate or 0)
                            )
                            salary_acc[employee.user_id] = salary_acc.get(
                                employee.user_id, Decimal("0")
                            ) + salary_value

                        # краткая запись по сотрудникам (без ставок)
                        emp_short = []
                        for employee in record.employees:
                            if employee.user_id == manager_id:
                                continue
                            name = user_map.get(employee.user_id, f"ID {employee.user_id}")
                            st = employee.start_time.strftime("%H:%M") if employee.start_time else "—"
                            en = employee.end_time.strftime("%H:%M") if employee.end_time else "—"
                            emp_short.append(f"{name} ({st}–{en})")

                        # компактная строка дня (для details)
                        days_lines.append(
                            f"  {current.strftime('%d.%m')}: Z {_fmt_decimal(cash)}, терм. {_fmt_decimal(terminal)}, "
                            f"нал. {_fmt_decimal(cash_processed)}, на руках {_fmt_decimal(cash_on_hand)}"
                        )
                        days_lines.append(
                            f"    Корректировки: цена {_fmt_decimal(changed_price)}, скидка {_fmt_decimal(discount)}, "
                            f"промо {_fmt_decimal(promotion)}, в магазин {_fmt_decimal(to_store)}, "
                            f"возврат {_fmt_decimal(refund)}, сервис {_fmt_decimal(service)}, "
                            f"чеки {_fmt_decimal(receipt)}, прочие {_fmt_decimal(expenses)}"
                        )
                        if emp_short:
                            days_lines.append("    Сотр.: " + ", ".join(emp_short))

                        totals["cash"] += cash
                        totals["terminal"] += terminal
                        totals["cash_processed"] += cash_processed
                        totals["cash_on_hand"] += cash_on_hand
                        totals["changed_price"] += changed_price
                        totals["discount"] += discount
                        totals["promotion"] += promotion
                        totals["to_store"] += to_store
                        totals["refund"] += refund
                        totals["service"] += service
                        totals["receipt"] += receipt
                        totals["expenses"] += expenses
                        totals["expense_total"] += expense_total
                        totals["cash_total"] += cash_total

                        days_presence[current] = True
                    else:
                        days_presence[current] = False

                    current += timedelta(days=1)

                vacation_records = await fetch_vacations(session, store.id, start, end)
                vacation_amounts = aggregate_vacation_amounts(vacation_records, start, end)
                for uid, amount in vacation_amounts.items():
                    salary_acc[uid] = salary_acc.get(uid, Decimal("0")) + amount

                salaries = summarize_salaries(salary_acc, payouts_map)

                # --- summary (для чата)
                s_lines = [
                    f"<b>Магазин {_esc(store.name)}</b> — {_esc(start.strftime('%d.%m.%Y'))}–{_esc(end.strftime('%d.%m.%Y'))}",
                    _mono_line([
                        ("Z", _fmt_decimal(totals["cash"])),
                        ("Терминал", _fmt_decimal(totals["terminal"])),
                        ("Наличные", _fmt_decimal(totals["cash_processed"])),
                    ]),
                    _mono_line([("На руках", _fmt_decimal(totals["cash_on_hand"]))]),
                    _mono_line([
                        ("Корр. цена", _fmt_decimal(totals["changed_price"])),
                        ("Скидка", _fmt_decimal(totals["discount"])),
                        ("Промо", _fmt_decimal(totals["promotion"])),
                        ("В магазин", _fmt_decimal(totals["to_store"])),
                        ("Возврат", _fmt_decimal(totals["refund"])),
                    ]),
                    _mono_line([
                        ("Сервис", _fmt_decimal(totals["service"])),
                        ("Чеки", _fmt_decimal(totals["receipt"])),
                        ("Прочие", _fmt_decimal(totals["expenses"])),
                    ]),
                    _mono_line([
                        ("Расход итого", _fmt_decimal(totals["expense_total"])),
                        ("Касса итого", _fmt_decimal(totals["cash_total"])),
                    ]),
                ]
                if salaries:
                    s_lines.append("<b>Зарплаты</b>")
                    total_paid = Decimal("0")
                    total_accrued = Decimal("0")
                    for item in salaries:
                        name = _esc(user_map.get(item["user_id"], f"ID {item['user_id']}"))
                        total_paid += Decimal(item["paid"])
                        total_accrued += Decimal(item["total"])
                        s_lines.append(
                            f"  {name}: начислено {_fmt_decimal(item['total'])}, "
                            f"выплачено {_fmt_decimal(item['paid'])}, остаток {_fmt_decimal(item['remaining'])}"
                        )
                    # (1) Итого ЗП за весь период
                    s_lines.append(_esc(f"Итого ЗП за весь период со всех сотрудников: {_fmt_decimal(total_accrued)}"))
                    # (2) Выплачено за период всего
                    s_lines.append(_esc(f"Выплачено за период всего: {_fmt_decimal(total_paid)}"))
                    # после (2): сколько осталось выплатить
                    remaining_total = total_accrued - total_paid
                    s_lines.append(_esc(f"Осталось выплатить за период всего: {_fmt_decimal(remaining_total)}"))

                if vacation_records:
                    vac_lines = []
                    for vac in vacation_records:
                        name = _esc(user_map.get(vac.user_id, f"ID {vac.user_id}"))
                        vac_lines.append(
                            f"{name}: {vac.start_date.strftime('%d.%m')}–{vac.end_date.strftime('%d.%m')} ({_fmt_decimal(vac.amount)})"
                        )
                    s_lines.append("Отпуска: " + "; ".join(vac_lines))

                # нет данных (свёртка)
                no_data_str = _collapse_no_data_days(days_presence)
                if no_data_str != "—":
                    s_lines.append(_esc("Нет данных: " + no_data_str))

                summaries.append("\n".join(s_lines))

                # --- details (для файла)
                d_lines = [
                    f"Магазин {store.name} — отчёт за период {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')}",
                    *days_lines,
                    "Итоги за период:",
                    f"  Z { _fmt_decimal(totals['cash']) }, терминал { _fmt_decimal(totals['terminal']) }, "
                    f"наличные { _fmt_decimal(totals['cash_processed']) }, на руках { _fmt_decimal(totals['cash_on_hand']) }",
                    f"  Корректировки: цена { _fmt_decimal(totals['changed_price']) }, скидка { _fmt_decimal(totals['discount']) }, "
                    f"промо { _fmt_decimal(totals['promotion']) }, в магазин { _fmt_decimal(totals['to_store']) }, "
                    f"возврат { _fmt_decimal(totals['refund']) }, сервис { _fmt_decimal(totals['service']) }, "
                    f"чеки { _fmt_decimal(totals['receipt']) }, прочие { _fmt_decimal(totals['expenses']) }",
                    f"  Расход итого { _fmt_decimal(totals['expense_total']) }, касса итого { _fmt_decimal(totals['cash_total']) }",
                ]
                if salaries:
                    d_lines.append("Зарплаты по сотрудникам:")
                    for item in salaries:
                        name = user_map.get(item["user_id"], f"ID {item['user_id']}")
                        d_lines.append(
                            f"  {name}: начислено {_fmt_decimal(item['total'])}, "
                            f"выплачено {_fmt_decimal(item['paid'])}, остаток {_fmt_decimal(item['remaining'])}"
                        )
                    total_paid = sum(Decimal(x["paid"]) for x in salaries)
                    total_accrued = sum(Decimal(x["total"]) for x in salaries)
                    remaining_total = total_accrued - total_paid
                    d_lines.append(f"Итого ЗП за весь период со всех сотрудников: {_fmt_decimal(total_accrued)}")
                    d_lines.append(f"Выплачено за период всего: {_fmt_decimal(total_paid)}")
                    d_lines.append(f"Осталось выплатить за период всего: {_fmt_decimal(remaining_total)}")

                if vacation_records:
                    vac_lines = []
                    for vac in vacation_records:
                        name = user_map.get(vac.user_id, f"ID {vac.user_id}")
                        vac_lines.append(
                            f"{name}: {vac.start_date.strftime('%d.%m')}–{vac.end_date.strftime('%d.%m')} ({_fmt_decimal(vac.amount)})"
                        )
                    d_lines.append("Отпуска в периоде: " + "; ".join(vac_lines))

                details_all.append("\n".join(d_lines))

    return summaries, "\n\n".join(details_all)

# -------- telegram send --------

def _split_message(message: str, limit: int = 4000) -> list[str]:
    if len(message) <= limit:
        return [message]
    parts: list[str] = []
    current = ""
    for line in message.splitlines():
        line = line.rstrip()
        candidate = f"{current}\n{line}".strip() if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = line
        else:
            chunk = line
            while len(chunk) > limit:
                parts.append(chunk[:limit])
                chunk = chunk[limit:]
            current = chunk
        if len(current) > limit:
            while len(current) > limit:
                parts.append(current[:limit])
                current = current[limit:]
    if current:
        parts.append(current)
    return [part for part in parts if part]

async def _send_telegram_messages(texts: Iterable[str]) -> None:
    messages = [text.strip() for text in texts if text.strip()]
    if not messages:
        return
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        for message in messages:
            print("[REPORT]", message)
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        for message in messages:
            for payload in _split_message(message):
                resp = await client.post(
                    f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                    data={
                        "chat_id": TG_CHAT_ID,
                        "text": payload,
                        "parse_mode": "HTML",              # офиц. параметр
                        "disable_web_page_preview": True,  # офиц. параметр
                    },
                )
                if resp.status_code != 200:
                    print("❌ Ошибка отправки отчёта:", resp.text)

async def _send_telegram_document(filename: str, content: str, caption: str | None = None) -> None:
    if not content.strip():
        return
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print(f"[REPORT_DOC] {filename}\n{content[:1000]}...\n")
        return

    # multipart/form-data для sendDocument (по Bot API)
    # https://core.telegram.org/bots/api#making-requests — для загрузки файлов требуется multipart/form-data
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {
            "document": (filename, content.encode("utf-8"), "text/plain"),
        }
        data = {
            "chat_id": TG_CHAT_ID,
        }
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        resp = await client.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument",
            data=data,
            files=files,
        )
        if resp.status_code != 200:
            print("❌ Ошибка отправки файла:", resp.text)

# -------- orchestration --------

async def _generate_and_send_reports(start: date, end: date) -> None:
    user_map = await _fetch_user_map()
    tiktok_coro = _collect_tiktok_report(start, end, user_map)
    stores_coro = _collect_store_reports(start, end, user_map)
    (tiktok_summary, tiktok_details), (store_summaries, store_details) = await asyncio.gather(
        tiktok_coro, stores_coro
    )

    # Сначала отправим файл (детализация общая)
    details_filename = f"reports_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.txt"
    full_details = "\n\n".join([tiktok_details, store_details])
    await _send_telegram_document(
        filename=details_filename,
        content=full_details,
        caption=f"<b>Детальный отчёт</b> {_esc(start.strftime('%d.%m.%Y'))}–{_esc(end.strftime('%d.%m.%Y'))}",
    )

    # Затем — компактные сводки текстом
    await _send_telegram_messages([tiktok_summary, *store_summaries])

@shared_task
def send_periodic_reports_task() -> None:
    today = date.today()
    period = _build_period_for_today(today)
    if not period:
        print(f"ℹ️ {today.isoformat()}: день не входит в график отправки отчётов")
        return
    start, end = period
    print("📊 Подготовка отчётов за период", start.isoformat(), "—", end.isoformat())
    asyncio.run(_generate_and_send_reports(start, end))
    print("✅ Отчёты подготовлены и отправлены")
