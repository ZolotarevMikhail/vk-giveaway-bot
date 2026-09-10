"""Настройки бота. Ключи берём из .env — в коде их быть не должно."""

import os

from dotenv import load_dotenv

load_dotenv()

# Токен сообщества ВК (получается в настройках группы, см. README)
VK_API_TOKEN = os.getenv("VK_API_TOKEN", "")
# ID сообщества, в котором работает бот (число, без минуса)
VK_GROUP_ID = os.getenv("VK_GROUP_ID", "")
# Версия API ВК — на момент разработки актуальна
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")

# ID админов через запятую: только они управляют розыгрышем
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}

DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "15"))


def is_admin(user_id: int) -> bool:
    """Является ли пользователь админом."""
    return user_id in ADMIN_IDS