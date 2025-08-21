from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.tokens import decode_token
from src.database import get_async_session
from src.users.models import User
from sqlalchemy.future import select


class OAuth2PasswordBearerWithCookie(HTTPBearer):
    async def __call__(self, request: Request) -> str:
        auth_header = request.headers.get("Authorization")
        cookie_auth = request.cookies.get("Authorization")
        scheme, param = get_authorization_scheme_param(auth_header or cookie_auth)
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Not authenticated")
        return param

oauth2_scheme = OAuth2PasswordBearerWithCookie()

async def get_current_user(
    token: str = Depends(oauth2_scheme), session: AsyncSession = Depends(get_async_session)
):
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return user


async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


async def get_manager_or_admin(current_user: User = Depends(get_current_user)):
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Managers or admins only")
    return current_user

async def get_cashier_or_manager_or_admin(current_user: User = Depends(get_current_user)):
    if current_user.role not in ["admin", "manager", "cashier"]:
        raise HTTPException(status_code=403, detail="Cashiers, managers or admins only")
    return current_user
