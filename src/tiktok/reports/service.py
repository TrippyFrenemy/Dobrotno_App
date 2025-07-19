from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.tiktok.orders.models import Order
from src.tiktok.returns.models import Return
from src.tiktok.shifts.models import Shift, ShiftAssignment, ShiftLocation
from src.users.models import User, UserRole
from src.tiktok.payouts.models import Payout


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
        employees = set()

        # Сотрудники по сменам
        for shift in shifts:
            assignments = [a for a in shift.assignments if a.user.role == UserRole.EMPLOYEE]
            employees.update(a.user_id for a in assignments)

            if shift.location == ShiftLocation.tiktok:
                if len(assignments) == 1:
                    ass = assignments[0]
                    fixed[ass.user_id] += ass.user.default_rate
                    percent[ass.user_id] += round(cashbox * ass.user.default_percent / 100)
                elif len(employees) == 2:
                    for e in assignments:
                        fixed[e.user_id] += e.user.default_rate
                        cashbox_perc = cashbox / len(employees)
                        percent[e.user_id] += round((cashbox_perc * e.user.default_percent) / 100)
            else:
                for a in assignments:
                    fixed[a.user_id] += round(a.user.default_rate)

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
            "employees": list(employees),
            "creators": list(day_orders.keys()),
        })

        current += timedelta(days=1)

    return result


async def get_payouts_for_period(session: AsyncSession, start: date, end: date, current_user: User):
    # Загружаем пользователей один раз
    users_q = await session.execute(select(User.id, User.role))
    user_roles = {uid: role for uid, role in users_q.all()}

    # Загружаем выплаты
    q = await session.execute(
        select(Payout.user_id, func.sum(Payout.amount))
        .where(and_(Payout.date >= start, Payout.date <= end))
        .group_by(Payout.user_id)
    )
    payouts = dict(q.all())

    # Фильтрация: если менеджер — не показываем выплаты администраторам
    if current_user.role == UserRole.MANAGER:
        payouts = {
            uid: amount
            for uid, amount in payouts.items()
            if user_roles.get(uid) != UserRole.ADMIN
        }

    return payouts

