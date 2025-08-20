import os
from datetime import date
import subprocess
import httpx
from celery import shared_task
from src.config import TG_BOT_TOKEN, TG_CHAT_ID, DB_NAME, DB_USER, DB_PASS, DB_HOST
import hashlib


def get_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

@shared_task
def send_db_backup_task():
    filename = f"/fastapi_app/tmp/backup_{DB_NAME}.sql"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    hash_path = filename + ".sha256"

    print(f"📦 Создание бекапа базы данных {DB_NAME}...")

    try:
        subprocess.run(
            ["pg_dump", "-h", DB_HOST, "-U", DB_USER, "-d", DB_NAME, "--exclude-table-data=user_logs", "-f", filename],
            check=True,
            env={**os.environ, "PGPASSWORD": DB_PASS}
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при создании дампа: {e}")
        return

    current_hash = get_file_hash(filename)
    old_hash = None

    if os.path.exists(hash_path):
        with open(hash_path, "r") as f:
            old_hash = f.read().strip()

    if current_hash == old_hash:
        print("⏩ Изменений в БД нет — бэкап не отправляется")
        return

    with open(hash_path, "w") as f:
        f.write(current_hash)

    print("✅ Бекап изменён. Отправка в Telegram...")
    try:
        with open(filename, "rb") as f:
            response = httpx.post(
                url=f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument",
                data={"chat_id": TG_CHAT_ID, "caption": f"Бэкап за {date.today()}"},
                files={"document": f}
            )
        if response.status_code == 200:
            print("✅ Бекап отправлен в Telegram")
        else:
            print(f"❌ Ошибка Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка при отправке в Telegram: {e}")
