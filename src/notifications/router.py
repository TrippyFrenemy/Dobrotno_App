from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from src.auth.dependencies import get_current_user, get_admin_user
from src.notifications.models import Notification, NotificationType
from src.users.models import User
from src.database import get_async_session
from src.utils.csrf import generate_csrf_token, verify_csrf_token

router = APIRouter(prefix="/notifications", tags=["Notifications"])

templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse)
async def list_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    """Список уведомлений текущего пользователя"""

    # Фильтры
    filters = [Notification.user_id == user.id]
    if unread_only:
        filters.append(Notification.is_read == False)

    # Подсчет общего количества
    stmt_count = select(func.count(Notification.id)).where(*filters)
    result_count = await session.execute(stmt_count)
    total = result_count.scalar() or 0

    # Получение уведомлений с пагинацией
    offset = (page - 1) * per_page
    stmt = (
        select(Notification)
        .where(*filters)
        .order_by(desc(Notification.created_at))
        .limit(per_page)
        .offset(offset)
    )
    result = await session.execute(stmt)
    notifications = result.scalars().all()

    # Подсчет непрочитанных
    stmt_unread = select(func.count(Notification.id)).where(
        Notification.user_id == user.id,
        Notification.is_read == False
    )
    result_unread = await session.execute(stmt_unread)
    unread_count = result_unread.scalar() or 0

    total_pages = (total + per_page - 1) // per_page

    csrf_token = await generate_csrf_token(user.id)

    return templates.TemplateResponse(
        "notifications/list.html",
        {
            "request": request,
            "user": user,
            "notifications": notifications,
            "unread_count": unread_count,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "unread_only": unread_only,
            "csrf_token": csrf_token,
        },
    )


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: int,
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    """Отметить уведомление как прочитанное"""

    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user.id
    )
    result = await session.execute(stmt)
    notification = result.scalar()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
        await session.commit()

    return RedirectResponse("/notifications", status_code=303)


@router.post("/read-all")
async def mark_all_as_read(
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    """Отметить все уведомления как прочитанные"""

    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    stmt = select(Notification).where(
        Notification.user_id == user.id,
        Notification.is_read == False
    )
    result = await session.execute(stmt)
    notifications = result.scalars().all()

    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.utcnow()

    await session.commit()

    return RedirectResponse("/notifications", status_code=303)


@router.post("/{notification_id}/delete")
async def delete_notification(
    notification_id: int,
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    """Удалить уведомление"""

    if not csrf_token or not await verify_csrf_token(user.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    stmt = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user.id
    )
    result = await session.execute(stmt)
    notification = result.scalar()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    await session.delete(notification)
    await session.commit()

    return RedirectResponse("/notifications", status_code=303)


@router.get("/create", response_class=HTMLResponse)
async def create_notification_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user),
):
    """Страница создания уведомления (только админ)"""

    # Получить список пользователей для выбора
    stmt = select(User).where(User.is_active == True).order_by(User.name)
    result = await session.execute(stmt)
    users = result.scalars().all()

    csrf_token = await generate_csrf_token(admin.id)

    return templates.TemplateResponse(
        "notifications/create.html",
        {
            "request": request,
            "user": admin,
            "users": users,
            "csrf_token": csrf_token,
        },
    )


@router.post("/create")
async def create_notification(
    user_ids: str = Form(...),  # comma-separated list or "all"
    title: str = Form(...),
    message: str = Form(...),
    type: str = Form("info"),
    related_url: Optional[str] = Form(None),
    csrf_token: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
    admin: User = Depends(get_admin_user),
):
    """Создать уведомление (только админ)"""

    if not csrf_token or not await verify_csrf_token(admin.id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    # Определяем целевых пользователей
    target_user_ids = []
    if user_ids.strip().lower() == "all":
        stmt = select(User.id).where(User.is_active == True)
        result = await session.execute(stmt)
        target_user_ids = [row[0] for row in result.all()]
    else:
        target_user_ids = [int(uid.strip()) for uid in user_ids.split(",") if uid.strip()]

    # Создаем уведомления для каждого пользователя
    for user_id in target_user_ids:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=NotificationType(type),
            related_url=related_url if related_url else None,
        )
        session.add(notification)

    await session.commit()

    return RedirectResponse("/notifications", status_code=303)


@router.get("/api/unread-count", response_class=JSONResponse)
async def get_unread_count(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(get_current_user),
):
    """API endpoint для получения количества непрочитанных уведомлений"""

    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user.id,
        Notification.is_read == False
    )
    result = await session.execute(stmt)
    unread_count = result.scalar() or 0

    return {"unread_count": unread_count}
