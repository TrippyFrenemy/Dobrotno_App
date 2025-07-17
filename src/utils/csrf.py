import secrets
import redis.asyncio as redis
from src.config import REDIS_HOST, REDIS_PORT, CSRF_TOKEN_EXPIRY

r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)

async def generate_csrf_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    await r.setex(f"csrf:{user_id}:{token}", CSRF_TOKEN_EXPIRY, "valid")
    return token

async def verify_csrf_token(user_id: int, token: str) -> bool:
    key = f"csrf:{user_id}:{token}"
    print(f"Verifying CSRF token: {key}")
    exists = await r.exists(key)
    if exists:
        await r.delete(key)
    return bool(exists)
