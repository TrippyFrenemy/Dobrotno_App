# src/logs/router.py
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from src.database import get_async_session
from src.auth.dependencies import get_admin_user
from src.logs.models import UserLog
from src.users.models import User

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")

@router.get("/", response_class=HTMLResponse)
async def show_logs(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user)
):
    offset = (page - 1) * limit

    # общее количество логов
    total_q = await session.execute(select(UserLog))
    total_logs = total_q.scalars().all()
    total_count = len(total_logs)
    total_pages = (total_count + limit - 1) // limit

    stmt = (
        select(UserLog)
        .options(joinedload(UserLog.user))
        .order_by(UserLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()

    return templates.TemplateResponse("logs/list.html", {
        "request": request,
        "logs": logs,
        "user": admin,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    })
