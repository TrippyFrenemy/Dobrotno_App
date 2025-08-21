from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.tiktok.orders.models import Order
from src.tiktok.returns.models import Return
from src.tiktok.shifts.models import Shift, ShiftAssignment, ShiftLocation
from src.users.models import User, UserRole
from src.payouts.models import Payout


def get_half_month_periods(month: int, year: int):
    first_half = (date(year, month, 1), date(year, month, 15))
    if month == 12:
        end_of_month = date(year, 12, 31)
    else:
        end_of_month = date(year, month + 1, 1) - timedelta(days=1)
    second_half = (date(year, month, 16), end_of_month)
    return first_half, second_half


async def get_monthly_report(
    session: AsyncSession, 
    start: date, 
    end: date,
    current_user: User    
):
    
    users_q = await session.execute(select(User))
    users = {u.id: u for u in users_q.scalars().all()}

    # Суммы заказов по дате и пользователю
    orders_q = await session.execute(
        select(Order.date, Order.created_by, func.sum(Order.amount))
        .where(Order.date >= start, Order.date <= end)
        .group_by(Order.date, Order.created_by)
    )
    orders_map = defaultdict(lambda: defaultdict(Decimal))
    for dt, uid, amount in orders_q.all():
        orders_map[dt][uid] += amount

    # Суммы возвратов по дате
    returns_q = await session.execute(
        select(Return.date, func.sum(Return.amount))
        .where(Return.date >= start, Return.date <= end)
        .group_by(Return.date)
    )
    returns_map = {dt: amount for dt, amount in returns_q.all()}

    # Все смены с назначениями
    shifts_q = await session.execute(
        select(Shift)
        .where(Shift.date >= start, Shift.date <= end)
        .options(selectinload(Shift.assignments).selectinload(ShiftAssignment.user))
    )
    shifts_by_date = defaultdict(list)
    for shift in shifts_q.scalars().all():
        shifts_by_date[shift.date].append(shift)

    # Единый проход по дням
    result = []
    current = start

    while current <= end:
        shifts = shifts_by_date.get(current, [])
        day_orders = orders_map.get(current, {})
        returns = returns_map.get(current, Decimal("0.00"))
        total_orders = sum(day_orders.values())
        cashbox = total_orders - returns

        fixed = defaultdict(Decimal)
        percent = defaultdict(Decimal)
        employee_details = []
        shift_id = shifts[0].id if shifts else None

        # Сотрудники по сменам
        for shift in shifts:
            assignments = [a for a in shift.assignments if a.user.role == UserRole.EMPLOYEE]
            
            if not assignments:
                continue

            if shift.location == ShiftLocation.tiktok:
                ratios = {}
                total_ratio = Decimal("0")
                for a in assignments:
                    def_hours = (
                        datetime.combine(date.today(), a.user.shift_end)
                        - datetime.combine(date.today(), a.user.shift_start)
                    ).total_seconds() / 3600 or 1
                    work_hours = (
                        datetime.combine(date.today(), a.end_time)
                        - datetime.combine(date.today(), a.start_time)
                    ).total_seconds() / 3600
                    ratio = Decimal(work_hours) / Decimal(def_hours)
                    ratios[a.user_id] = ratio
                    total_ratio += ratio
                    fixed[a.user_id] += Decimal(a.salary)
                    employee_details.append(
                        {
                            "user_id": a.user_id,
                            "start_time": a.start_time,
                            "end_time": a.end_time,
                            "salary": a.salary,
                        }
                    )

                for a in assignments:
                    cashbox_perc = cashbox / len(employee_details)
                    percent[a.user_id] += round((cashbox_perc * a.user.default_percent) / 100)
            else:
                for a in assignments:
                    fixed[a.user_id] += Decimal(a.salary)
                    employee_details.append(
                        {
                            "user_id": a.user_id,
                            "start_time": a.start_time,
                            "end_time": a.end_time,
                            "salary": a.salary,
                        }
                    )

        # Менеджеры/админы по заказам
        for uid, amount in day_orders.items():
            user = users.get(uid)
            if user and user.role in [UserRole.ADMIN, UserRole.MANAGER]:
                fixed[uid] += user.default_rate
                percent[uid] += round((amount - returns) * user.default_percent / 100)

        # Финальные суммы
        salary_by_user = {
            uid: fixed[uid] + percent[uid]
            for uid in set(fixed) | set(percent)
            if not (current_user.role == UserRole.MANAGER and users.get(uid).role == UserRole.ADMIN)
        }
        salary_fixed_by_user = {
            uid: fixed[uid]
            for uid in fixed
            if not (current_user.role == UserRole.MANAGER and users.get(uid).role == UserRole.ADMIN)
        }
        salary_percent_by_user = {
            uid: percent[uid]
            for uid in percent
            if not (current_user.role == UserRole.MANAGER and users.get(uid).role == UserRole.ADMIN)
        }

        result.append({
            "date": current,
            "orders": total_orders,
            "returns": returns,
            "cashbox": cashbox,
            "salary_by_user": salary_by_user,
            "salary_fixed_by_user": salary_fixed_by_user,
            "salary_percent_by_user": salary_percent_by_user,
            "employees": employee_details,
            "creators": list(day_orders.keys()),
            "shift_id": shift_id,
        })

        current += timedelta(days=1)

    return result


async def get_payouts_for_period(session: AsyncSession, start: date, end: date, current_user: User):
    stmt = (
        select(Payout.user_id, func.sum(Payout.amount))
        .join(User, User.id == Payout.user_id)
        .where(Payout.date >= start, Payout.date <= end)
    )

    if current_user.role == UserRole.MANAGER:
        stmt = stmt.where(User.role != UserRole.ADMIN)

    stmt = stmt.group_by(Payout.user_id)
    q = await session.execute(stmt)
    return dict(q.all())


def summarize_period(days: list[dict], payouts: dict[int, Decimal]):
    total_orders = Decimal("0")
    total_returns = Decimal("0")
    salary_acc = defaultdict(lambda: {"fixed": Decimal("0"), "percent": Decimal("0")})

    for day in days:
        total_orders += day["orders"]
        total_returns += day["returns"]

        for uid, amount in day["salary_fixed_by_user"].items():
            salary_acc[uid]["fixed"] += amount
        for uid, amount in day["salary_percent_by_user"].items():
            salary_acc[uid]["percent"] += amount

    salaries = []
    for uid, parts in salary_acc.items():
        fixed = parts["fixed"]
        percent = parts["percent"]
        total = fixed + percent
        paid = payouts.get(uid, Decimal("0"))
        salaries.append(
            {
                "user_id": uid,
                "fixed": fixed,
                "percent": percent,
                "total": total,
                "paid": paid,
                "remaining": total - paid,
            }
        )

    return {
        "days": days,
        "totals": {
            "orders": total_orders,
            "returns": total_returns,
            "cashbox": total_orders - total_returns,
        },
        "salaries": salaries,
    }
