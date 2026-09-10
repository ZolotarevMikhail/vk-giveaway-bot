"""Логика бота-розыгрыша: обработка сообщений участников и админ-команд."""

import logging

import giveaway_db as db
from config import is_admin
from vk_api_client import VkApiClient

logger = logging.getLogger(__name__)

WELCOME = (
    "🎁 Привет! Хочешь участвовать в розыгрыше?\n"
    'Нажми кнопку «Участвовать» ниже.'
)

ALREADY = "Ты уже участвуешь в этом розыгрыше — не переживай, всё сохранили ✅"

JOINED = "🎉 Ты в игре! Победителя выберем случайно по окончании розыгрыша. Удачи!"

NOT_SUBSCRIBED = (
    "Чтобы участвовать, нужно быть подписанным на {titles}.\n"
    "Подпишись и нажми «Участвовать» ещё раз."
)

SUB_CHECK_FAILED = (
    "Не удалось проверить подписку (сбой ВКонтакте). Попробуй ещё раз через минуту."
)

HELP = (
    "Команды админа:\n"
    "/сообщества — список обязательных сообществ\n"
    "/добавить короткое_имя — добавить сообщество\n"
    "/удалить короткое_имя — убрать сообщество\n"
    "/статус — участников, дата окончания\n"
    "/конец ГГГГ-ММ-ДД — задать дату окончания\n"
    "/сброс — новый раунд (список участников обнуляется)\n"
    "/победитель — выбрать случайного победителя"
)

WINNER = "🏆 Победитель розыгрыша: {name} — https://vk.com/id{uid}\nПоздравляем!"


def _part_keyboard() -> dict:
    """Кнопка «Участвовать» — одно нажатие, и ты в розыгрыше."""
    return {
        "one_time": False,
        "buttons": [[{
            "action": {"type": "text", "label": "Участвовать", "payload": "{}"},
            "color": "positive",
        }]],
    }


class GiveawayBot:
    def __init__(self, vk: VkApiClient):
        self.vk = vk

    async def handle(self, user_id: int, text: str) -> tuple[str, dict | None]:
        """Возвращает (текст ответа, клавиатура или None)."""
        text = (text or "").strip()

        if is_admin(user_id) and text.startswith("/"):
            return await self._admin_command(text)

        lowered = text.lower()
        if lowered in ("начать", "start"):
            return WELCOME, _part_keyboard()
        if lowered == "участвовать":
            return await self._join(user_id)

        return WELCOME, _part_keyboard()

    # ---------- Участие ----------

    async def _join(self, user_id: int) -> tuple[str, dict | None]:
        groups = db.list_groups()
        round_id, _ = db.current_round()

        # Защита от повторов: 1 человек = 1 участие
        if any(uid == user_id for uid, _ in db.participants(round_id)):
            return ALREADY, _part_keyboard()

        # Проверка подписки на все обязательные сообщества
        missing = []
        titles = []
        for g in groups:
            member = await self.vk.is_member(g, user_id)
            if member is None:  # сбой API — не пускаем, просим повторить
                return SUB_CHECK_FAILED, _part_keyboard()
            if not member:
                missing.append(g)
                titles.append(await self.vk.group_title(g))

        if missing:
            return NOT_SUBSCRIBED.format(titles=", ".join(titles)), _part_keyboard()

        name = await self._first_name(user_id)
        db.add_participant(round_id, user_id, name)
        return JOINED, _part_keyboard()

    async def _first_name(self, user_id: int) -> str:
        resp = await self.vk._call("users.get", user_ids=str(user_id))
        if resp and isinstance(resp, list) and resp:
            return resp[0].get("first_name", "")
        return ""

    # ---------- Админ-команды ----------

    async def _admin_command(self, text: str) -> tuple[str, dict | None]:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/помощь", "/help", "/старт"):
            return HELP, None

        if cmd == "/сообщества":
            groups = db.list_groups()
            return (
                ("Обязательные сообщества:\n" + "\n".join(f"• {g}" for g in groups))
                if groups else "Обязательных сообществ пока нет. Добавь: /добавить короткое_имя"
            ), None

        if cmd == "/добавить":
            if not arg:
                return "Укажи короткое имя: /добавить имя_сообщества", None
            name = arg.lstrip("https://vk.com/").strip("/").lower()
            added = db.add_group(name)
            return (
                f"✅ Добавлено: {name}" if added else f"⚠️ {name} уже в списке"
            ), None

        if cmd == "/удалить":
            if not arg:
                return "Укажи короткое имя: /удалить имя_сообщества", None
            name = arg.lstrip("https://vk.com/").strip("/").lower()
            removed = db.remove_group(name)
            return (
                f"✅ Удалено: {name}" if removed else f"⚠️ {name} нет в списке"
            ), None

        if cmd == "/статус":
            round_id, ends_at = db.current_round()
            n = len(db.participants(round_id))
            return (
                f"Раунд №{round_id}. Участников: {n}."
                + (f" Окончание: {ends_at}." if ends_at else " Дата окончания не задана.")
            ), None

        if cmd == "/конец":
            if not arg:
                return "Формат: /конец ГГГГ-ММ-ДД", None
            db.set_end_date(arg)
            return f"✅ Дата окончания: {arg}", None

        if cmd == "/сброс":
            new_id = db.reset_round()
            return f"✅ Розыгрыш сброшен. Новый раунд №{new_id} — участники с чистого листа.", None

        if cmd == "/победитель":
            round_id, ends_at = db.current_round()
            if ends_at and ends_at > db_list_today():
                return f"Розыгрыш ещё идёт до {ends_at}. Выбрать победителя можно после окончания.", None
            winner = db.pick_winner(round_id)
            if not winner:
                return "Участников пока нет — победителя выбирать не из кого.", None
            return WINNER.format(name=winner[1] or "участник", uid=winner[0]), None

        return "Неизвестная команда. /помощь — список команд.", None


def db_list_today() -> str:
    """Сегодняшняя дата в формате ГГГГ-ММ-ДД (для сравнения с датой окончания)."""
    from datetime import date
    return date.today().isoformat()