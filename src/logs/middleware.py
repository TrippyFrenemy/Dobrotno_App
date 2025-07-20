from datetime import datetime
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import async_session_maker
from src.logs.models import UserLog
from src.auth.tokens import decode_token
from src.users.models import User
import re
import os

from src.utils.ip import get_real_ip

logfile_path = "/fastapi_app/logs/user_activity.log"
os.makedirs(os.path.dirname(logfile_path), exist_ok=True)

logger = logging.getLogger("user_logger")
handler = logging.FileHandler(logfile_path)
logger.setLevel(logging.INFO)
logger.addHandler(handler)


class LogUserActionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get("Authorization", "").replace("Bearer ", "")
        user_id = None
        if token:
            try:
                payload = decode_token(token)
                user_id = int(payload.get("sub"))
            except:
                pass

        path = request.url.path
        method = request.method
        query = str(request.url.query)
        ip = await get_real_ip(request)
        ua = request.headers.get("user-agent", "unknown")

        skip = re.match(r"/(static|favicon|auth/refresh)", path)
        if skip:
            return await call_next(request)

        response = await call_next(request)
        status_code = response.status_code

        logger.info(f"[{datetime.now()}] {ip} {user_id} {method} {path}?{query} UA={ua} {status_code}")

        async with async_session_maker() as session:
            log = UserLog(
                user_id=user_id,
                action=f"{method} {path}" + (f"?{query}" if query else ""),
                path=path,
                ip_address=ip,
                user_agent=ua[:250],
                status_code=status_code,
                query_string=query
            )
            session.add(log)
            await session.commit()

        return response

        