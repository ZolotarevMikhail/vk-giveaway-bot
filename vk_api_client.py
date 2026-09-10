"""Работа с VK API: проверка подписки, отправка сообщений с кнопками."""

import json
import logging

import httpx

from config import REQUEST_TIMEOUT, VK_API_TOKEN, VK_API_VERSION

logger = logging.getLogger(__name__)

API_URL = "https://api.vk.com/method/{method}"


class VkApiClient:
    """Клиент VK API. Все вызовы идут от имени сообщества."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    async def close(self):
        await self.client.aclose()

    async def _call(self, method: str, **params):
        """Один вызов к VK API. Возвращает response или None при ошибке."""
        params.update({"access_token": VK_API_TOKEN, "v": VK_API_VERSION})
        try:
            resp = await self.client.post(API_URL.format(method=method), data=params)
            data = resp.json()
        except Exception as exc:
            logger.error("VK API %s: сетевая ошибка %s", method, exc)
            return None

        if "error" in data:
            err = data["error"]
            logger.error("VK API %s: ошибка %s — %s", method, err.get("error_code"), err.get("error_msg"))
            return None
        return data.get("response")

    # ---------- Подписки ----------

    async def is_member(self, group: str, user_id: int) -> bool | None:
        """Подписан ли user_id на сообщество group (короткое имя или id).
        None — не удалось проверить (сбой сети/API)."""
        resp = await self._call(
            "groups.isMember", group=group, user_id=user_id
        )
        if resp is None:
            return None
        return bool(resp.get("member"))

    async def group_title(self, group: str) -> str:
        """Название сообщества по короткому имени — для понятных ответов."""
        resp = await self._call(
            "groups.getById", group_id=group, fields="name"
        )
        if resp and isinstance(resp, dict):
            groups = resp.get("groups") or []
            if groups:
                return groups[0].get("name", group)
        return group

    # ---------- Сообщения ----------

    async def send(self, user_id: int, text: str, keyboard: dict | None = None) -> bool:
        """Отправляет сообщение участнику от имени сообщества."""
        params = {
            "user_id": user_id,
            "message": text,
            "random_id": 0,  # 0 = VK сам обеспечит уникальность
        }
        if keyboard:
            # ВК требует кнопки одной строкой JSON
            params["keyboard"] = json.dumps(keyboard)
        resp = await self._call("messages.send", **params)
        return resp is not None