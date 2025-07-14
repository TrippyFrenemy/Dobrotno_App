from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.orders.models import Order
from src.returns.models import Return
from src.shifts.models import Shift, ShiftAssignment, ShiftLocation
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


async def get_cash_and_returns(session: AsyncSession, target_date: date):
    # Касса (сумма заказов)
    orders_q = await session.execute(
        select(func.sum(Order.amount)).where(Order.date == target_date)
    )
    orders = orders_q.scalar() or Decimal("0.00")

    # Возвраты
    returns_q = await session.execute(
        select(func.sum(Return.amount)).where(Return.date == target_date)
    )
    returns = returns_q.scalar() or Decimal("0.00")

    return orders, returns


async def calc_daily_salary(session: AsyncSession, target_date: date, orders_amount: Decimal, returns_amount: Decimal):
    shifts_q = await session.execute(
        select(Shift)
        .where(Shift.date == target_date)
        .options(selectinload(Shift.assignments).selectinload(ShiftAssignment.user))
    )
    shifts = shifts_q.scalars().all()

    cashbox = orders_amount - returns_amount

    fixed = defaultdict(Decimal)
    percent = defaultdict(Decimal)

    for shift in shifts:
        assignments = shift.assignments
        employees = [a for a in assignments if a.user.role == UserRole.EMPLOYEE]

        # 💰 Сотрудники TikTok — % от кассы
        if shift.location == ShiftLocation.tiktok:
            if len(employees) == 1:
                employee = employees[0]
                fixed[employee.user_id] += employee.user.default_rate
                percent[employee.user_id] += round(cashbox * employee.user.default_percent * 2 / 100, 2)
            elif len(employees) == 2:
                for e in employees:
                    fixed[e.user_id] += e.user.default_rate
                    percent[e.user_id] += round(cashbox * e.user.default_percent / 100, 2)

        # 💼 Сотрудники обычных локаций — ставка
        else:
            for a in employees:
                fixed[a.user_id] += round(a.user.default_rate, 2)

        # 👤 Создатель смены — админ или менеджер
        creator_result = await session.execute(select(User).where(User.id == shift.created_by))
        creator = creator_result.scalar_one_or_none()

        if creator and creator.role in [UserRole.ADMIN, UserRole.MANAGER]:
            if shift.location == ShiftLocation.tiktok:
                fixed[creator.id] += creator.default_rate
                percent[creator.id] += round(cashbox * creator.default_percent / 100, 2)
            else:
                fixed[creator.id] += round(creator.default_rate, 2)

    return {
        "fixed": dict(fixed),
        "percent": dict(percent)
    }

async def get_monthly_report(session: AsyncSession, start: date, end: date):
    result = []
    current = start

    # Глобальные словари по пользователям
    fixed_by_user = defaultdict(Decimal)
    percent_by_user = defaultdict(Decimal)

    while current <= end:
        orders, returns = await get_cash_and_returns(session, current)
        salary = await calc_daily_salary(session, current, orders, returns)

        # Сумма всех зарплат за день (для html)
        salary_by_user = defaultdict(Decimal)
        for uid in set(salary["fixed"]) | set(salary["percent"]):
            f = salary["fixed"].get(uid, 0)
            p = salary["percent"].get(uid, 0)
            salary_by_user[uid] = f + p
            fixed_by_user[uid] += f
            percent_by_user[uid] += p

        result.append({
            "date": current,
            "orders": orders,
            "returns": returns,
            "cashbox": orders - returns,
            "salary_by_user": dict(salary_by_user),
            "salary_fixed_by_user": salary["fixed"],
            "salary_percent_by_user": salary["percent"],
        })

        current += timedelta(days=1)

    return result

async def get_payouts_for_period(session: AsyncSession, start: date, end: date):
    q = await session.execute(
        select(Payout.user_id, func.sum(Payout.amount))
        .where(and_(Payout.date >= start, Payout.date <= end))
        .group_by(Payout.user_id)
    )
    return dict(q.all())