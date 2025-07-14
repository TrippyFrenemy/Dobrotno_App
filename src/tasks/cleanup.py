from datetime import datetime, timedelta
from sqlalchemy import delete
from src.database import async_session_maker
from src.logs.models import UserLog
from celery import shared_task

@shared_task
def clean_old_logs():
    async def _clean():
        async with async_session_maker() as session:
            cutoff = datetime.utcnow() - timedelta(days=7)
            await session.execute(delete(UserLog).where(UserLog.timestamp < cutoff))
            await session.commit()
    import asyncio
    asyncio.run(_clean())
