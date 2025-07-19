import redis.asyncio as redis

from src.config import REDIS_HOST, REDIS_PORT

redis_client = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)

# Настройки
MAX_ATTEMPTS = 5
BLOCK_TIME = 10 * 60  # 10 минут в секундах

async def is_blocked(ip: str) -> bool:
    key = f"login_block:{ip}"
    attempts = await redis_client.get(key)
    return attempts is not None and int(attempts) >= MAX_ATTEMPTS

async def register_failed_attempt(ip: str):
    key = f"login_block:{ip}"
    # Увеличиваем счётчик + устанавливаем TTL
    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, BLOCK_TIME)

async def delete_attempt(ip: str):
    await redis_client.delete(f"login_block:{ip}")
