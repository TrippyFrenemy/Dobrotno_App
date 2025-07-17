from dotenv import load_dotenv
import os

load_dotenv()

DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")

REDIS_PORT = os.environ.get("REDIS_PORT")
REDIS_HOST = os.environ.get("REDIS_HOST")

SECRET = os.environ.get("SECRET")
SECRET_MANAGER = os.environ.get("SECRET_MANAGER")

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_NAME = os.environ.get("ADMIN_NAME")
ADMIN_ROLE = os.environ.get("ADMIN_ROLE")

CSRF_TOKEN_EXPIRY = int(os.environ.get("CSRF_TOKEN_EXPIRY"))

CELERY_BACHUP_RATE = int(os.environ.get("CELERY_BACHUP_RATE"))
