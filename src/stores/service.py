from collections import defaultdict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from src.config import MANAGER_EMAIL
from src.users.models import User, UserRole
from src.payouts.models import Payout, Location
from src.stores.models import StoreVacation


async def compute_salary(
    session: AsyncSession, assignments: List[tuple[int, str | None, str | None]]
) -> tuple[Decimal, dict[int, Decimal]]:
    """Calculate total salary and per-user amounts based on worked hours."""
    if not assignments:
        return Decimal("0.00"), {}
    ids = [uid for uid, _, _ in assignments]
    q = await session.execute(select(User).where(User.id.in_(ids)))
    users = {u.id: u for u in q.scalars().all()}

    def _to_time(value: str | None, fallback: time) -> time:
        return time.fromisoformat(value) if value else fallback

    total = Decimal("0.00")
    per_user: dict[int, Decimal] = {}
    for uid, start_s, end_s in assignments:
        user = users.get(uid)
        if not user:
            continue
        start_t = _to_time(start_s, user.shift_start)
        end_t = _to_time(end_s, user.shift_end)
        def_hours = (
            datetime.combine(date.today(), user.shift_end)
            - datetime.combine(date.today(), user.shift_start)
        ).total_seconds() / 3600 or 1
        work_hours = (
            datetime.combine(date.today(), end_t)
            - datetime.combine(date.today(), start_t)
        ).total_seconds() / 3600
        coeff = Decimal(work_hours) / Decimal(def_hours)
        amount = (user.default_rate * coeff).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_user[uid] = amount
        total += amount
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), per_user

async def get_config_manager(session: AsyncSession) -> User | None:
    if not MANAGER_EMAIL:
        return None
    q = await session.execute(
        select(User).where(User.email == MANAGER_EMAIL, User.is_active == True)
    )
    return q.scalars().first()


async def get_payouts_for_period(
    session: AsyncSession, start: date, end: date, current_user: User
):
    stmt = (
        select(Payout.user_id, func.sum(Payout.amount))
        .join(User, User.id == Payout.user_id)
        .where(
            Payout.date >= start,
            Payout.date <= end,
            Payout.location == Location.Store,
        )
    )

    if current_user.role == UserRole.MANAGER:
        stmt = stmt.where(User.role != UserRole.ADMIN)

    stmt = stmt.group_by(Payout.user_id)
    q = await session.execute(stmt)
    return {uid: amt or Decimal("0") for uid, amt in q.all()}


def summarize_salaries(salary_acc: dict[int, Decimal], payouts: dict[int, Decimal]):
    salaries = []
    for uid, amount in salary_acc.items():
        paid = payouts.get(uid, Decimal("0"))
        salaries.append(
            {
                "user_id": uid,
                "total": amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
                "paid": paid.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
                "remaining": (amount - paid).quantize(Decimal("1"), rounding=ROUND_HALF_UP),
            }
        )
    return salaries


def summarize_vacations(vac_acc: dict[int, Decimal]):
    vacations = []
    for uid, amount in vac_acc.items():
        vacations.append(
            {
                "user_id": uid,
                "total": amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
            }
        )
    return vacations


async def get_vacations_for_period(session: AsyncSession, store_id: int, start: date, end: date):
    stmt = select(StoreVacation).where(
        StoreVacation.store_id == store_id,
        StoreVacation.start_date <= end,
        StoreVacation.end_date >= start,
    )
    q = await session.execute(stmt)
    records = q.scalars().all()
    acc: dict[int, Decimal] = defaultdict(Decimal)
    for r in records:
        total_days = (r.end_date - r.start_date).days + 1
        overlap_start = max(r.start_date, start)
        overlap_end = min(r.end_date, end)
        overlap_days = (overlap_end - overlap_start).days + 1
        amount = Decimal(r.amount) * Decimal(overlap_days) / Decimal(total_days)
        acc[r.user_id] += amount
    return acc

def aggregate_vacation_amounts(
    records: List[StoreVacation], start: date, end: date
) -> dict[int, Decimal]:
    acc: dict[int, Decimal] = defaultdict(Decimal)
    for r in records:
        total_days = (r.end_date - r.start_date).days + 1
        overlap_start = max(r.start_date, start)
        overlap_end = min(r.end_date, end)
        overlap_days = (overlap_end - overlap_start).days + 1
        amount = Decimal(r.amount) * Decimal(overlap_days) / Decimal(total_days)
        acc[r.user_id] += amount
    return acc


async def fetch_vacations(
    session: AsyncSession, store_id: int, start: date, end: date
) -> List[StoreVacation]:
    stmt = select(StoreVacation).where(
        StoreVacation.store_id == store_id,
        StoreVacation.start_date <= end,
        StoreVacation.end_date >= start,
    )
    q = await session.execute(stmt)
    return q.scalars().all()
