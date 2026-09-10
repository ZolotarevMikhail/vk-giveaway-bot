"""Запуск бота через VK Long Poll.
Бот слушает сообщения сообщества и отвечает. При сбоях сам переподключается —
работает 24/7 без присмотра."""

import asyncio
import logging
import sys

from bot import GiveawayBot
from config import VK_API_TOKEN, VK_API_VERSION, VK_GROUP_ID
from giveaway_db import init_db
from vk_api_client import VkApiClient

logger = logging.getLogger(__name__)


async def get_long_poll_server(vk: VkApiClient):
    """Адрес, по которому бот получает новые сообщения."""
    return await vk._call(
        "groups.getLongPollServer", group_id=VK_GROUP_ID
    )


async def run():
    init_db()
    logger.info("Запуск бота-розыгрыша. Сообщество: %s", VK_GROUP_ID or "(не задано)")

    vk = VkApiClient()
    bot = GiveawayBot(vk)

    server_info = await get_long_poll_server(vk)
    if not server_info:
        logger.error("Нет связи с ВК. Проверь VK_API_TOKEN и VK_GROUP_ID в .env")
        return

    server, key, ts = server_info["server"], server_info["key"], server_info["ts"]
    logger.info("Бот запущен и слушает сообщения.")

    while True:
        try:
            url = f"{server}?act=a_check&key={key}&ts={ts}&wait=25"
            # ВК держит соединение 25 сек. в ожидании сообщений —
            # таймаут клиента должен быть больше, иначе связь будет рваться
            resp = await vk.client.get(url, timeout=40)
            data = resp.json()
        except Exception as exc:
            logger.error("Сбой связи: %s — переподключение через 5 сек.", exc)
            await asyncio.sleep(5)
            continue

        if "failed" in data:
            code = data.get("failed")
            if code in (2, 3):  # устарел ключ или история — берём сервер заново
                server_info = await get_long_poll_server(vk)
                if not server_info:
                    await asyncio.sleep(5)
                    continue
                server, key, ts = (
                    server_info["server"], server_info["key"], server_info["ts"],
                )
            elif code == 1:  # потерян ts — берём новый из ответа
                ts = data.get("ts", ts)
            await asyncio.sleep(1)
            continue

        ts = data.get("ts", ts)
        for update in data.get("updates", []):
            if update.get("type") != "message_new":
                continue
            message = update.get("object", {}).get("message", update.get("object", {}))
            user_id = message.get("from_id") or 0
            text = message.get("text", "")

            if user_id <= 0:  # сообщения самого сообщества игнорируем
                continue

            try:
                answer, keyboard = await bot.handle(user_id, text)
                await vk.send(user_id, answer, keyboard)
                logger.info("Ответ %s: %s", user_id, answer[:60])
            except Exception:
                logger.exception("Ошибка обработки сообщения от %s", user_id)


if __name__ == "__main__":
    if not VK_API_TOKEN:
        print("Нет VK_API_TOKEN. Скопируй .env.example в .env и заполни (см. README).")
        raise SystemExit(1)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nБот остановлен.")