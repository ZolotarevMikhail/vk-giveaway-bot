"""Логика бота-розыгрыша: обработка сообщений участников и админ-команд.

Администратор задаёт обязательные сообщества и дату окончания,
остальные участники проходят проверку подписки и попадают в раунд.
"""

import logging
from datetime import date

import giveaway_db as db
from config import is_admin
from vk_api_client import VkApiClient

logger = logging.getLogger(__name__)

# Префикс ссылки на сообщество — срезается из аргументов админ-команд
VK_URL_PREFIX = "https://vk.com/"

WELCOME = (
    "🎁 Привет! Хочешь участвовать в розыгрыше?\n"
    'Нажми кнопку «Участвовать» ниже.'
)

ALREADY = "Ты уже участвуешь в этом розыгрыше — не переживай, всё сохранили ✅"

JOINED = (
    "🎉 Ты в игре! Победителя выберем случайно "
    "по окончании розыгрыша. Удачи!"
)

NOT_SUBSCRIBED = (
    "Чтобы участвовать, нужно быть подписанным на {titles}.\n"
    "Подпишись и нажми «Участвовать» ещё раз."
)

SUB_CHECK_FAILED = (
    "Не удалось проверить подписку (сбой ВКонтакте). "
    "Попробуй ещё раз через минуту."
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

WINNER = (
    "🏆 Победитель розыгрыша: {name} — "
    "https://vk.com/id{uid}\nПоздравляем!"
)


def _part_keyboard() -> dict:
    """Кнопка «Участвовать» — одно нажатие, и ты в розыгрыше."""
    participate_action = {
        "type": "text",
        "label": "Участвовать",
        "payload": "{}",
    }
    return {
        "one_time": False,
        "buttons": [[{"action": participate_action, "color": "positive"}]],
    }


def _clean_group_name(arg: str) -> str:
    """Короткое имя сообщества: срезает ссылку ВК и слэши, в нижний регистр.

    Нюанс исходного кода: lstrip() убирает по одному символу из набора,
    а не подстроку целиком — поведение сохранено как есть.
    """
    return arg.lstrip(VK_URL_PREFIX).strip("/").lower()


class GiveawayBot:
    """Бот: отвечает участникам и выполняет админ-команды."""

    def __init__(self, vk: VkApiClient):
        self.vk = vk

    async def handle(self, user_id: int, text: str) -> tuple[str, dict | None]:
        """Возвращает (текст ответа, клавиатура или None)."""
        text = (text or "").strip()
        text_lower = text.lower()

        if is_admin(user_id) and text.startswith("/"):
            return await self._admin_command(text)

        if text_lower in ("начать", "start"):
            return WELCOME, _part_keyboard()
        if text_lower == "участвовать":
            return await self._join(user_id)

        return WELCOME, _part_keyboard()

    # ---------- Участие ----------

    async def _join(self, user_id: int) -> tuple[str, dict | None]:
        """Участие: проверка повторов и подписки
        на все обязательные сообщества."""
        round_id, _ = db.current_round()

        # Защита от повторов: 1 человек = 1 участие за раунд
        already_in = any(
            uid == user_id for uid, _ in db.participants(round_id)
        )
        if already_in:
            return ALREADY, _part_keyboard()

        # Проверяем каждую требуемую подписку; сбой API (None) не пропускаем
        missing = []
        titles = []
        for community in db.list_groups():
            member = await self.vk.is_member(community, user_id)
            if member is None:
                return SUB_CHECK_FAILED, _part_keyboard()
            if not member:
                missing.append(community)
                titles.append(await self.vk.group_title(community))

        if missing:
            return (
                NOT_SUBSCRIBED.format(titles=", ".join(titles)),
                _part_keyboard(),
            )

        name = await self._first_name(user_id)
        db.add_participant(round_id, user_id, name)
        return JOINED, _part_keyboard()

    async def _first_name(self, user_id: int) -> str:
        """Имя участника для поздравления
        победителя (пустое, если ВК не дал)."""
        resp = await self.vk._call("users.get", user_ids=str(user_id))
        if resp and isinstance(resp, list) and resp:
            return resp[0].get("first_name", "")
        return ""

    # ---------- Админ-команды ----------

    async def _admin_command(self, text: str) -> tuple[str, dict | None]:
        """Разбор и выполнение одной админ-команды."""
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/помощь", "/help", "/старт"):
            return HELP, None

        if cmd == "/сообщества":
            return self._groups_reply()
        if cmd == "/добавить":
            return self._add_group_reply(arg)
        if cmd == "/удалить":
            return self._remove_group_reply(arg)
        if cmd == "/статус":
            return self._status_reply()
        if cmd == "/конец":
            return self._set_end_reply(arg)
        if cmd == "/сброс":
            return self._reset_reply()
        if cmd == "/победитель":
            return self._winner_reply()

        return "Неизвестная команда. /помощь — список команд.", None

    def _groups_reply(self) -> tuple[str, None]:
        """Список обязательных сообществ для админа."""
        groups = db.list_groups()
        if not groups:
            return ("Обязательных сообществ пока нет. "
                    "Добавь: /добавить короткое_имя"), None
        listing = "\n".join(f"• {community}" for community in groups)
        return ("Обязательные сообщества:\n" + listing), None

    def _add_group_reply(self, arg: str) -> tuple[str, None]:
        """Добавляет сообщество в обязательные."""
        if not arg:
            return "Укажи короткое имя: /добавить имя_сообщества", None
        name = _clean_group_name(arg)
        added = db.add_group(name)
        if added:
            return f"✅ Добавлено: {name}", None
        return f"⚠️ {name} уже в списке", None

    def _remove_group_reply(self, arg: str) -> tuple[str, None]:
        """Убирает сообщество из обязательных."""
        if not arg:
            return "Укажи короткое имя: /удалить имя_сообщества", None
        name = _clean_group_name(arg)
        removed = db.remove_group(name)
        if removed:
            return f"✅ Удалено: {name}", None
        return f"⚠️ {name} нет в списке", None

    def _status_reply(self) -> tuple[str, None]:
        """Число участников и дата окончания текущего раунда."""
        round_id, ends_at = db.current_round()
        participant_count = len(db.participants(round_id))
        if ends_at:
            ending = f" Окончание: {ends_at}."
        else:
            ending = " Дата окончания не задана."
        summary = f"Раунд №{round_id}. Участников: {participant_count}."
        return summary + ending, None

    def _set_end_reply(self, arg: str) -> tuple[str, None]:
        """Задаёт дату окончания раунда."""
        if not arg:
            return "Формат: /конец ГГГГ-ММ-ДД", None
        db.set_end_date(arg)
        return f"✅ Дата окончания: {arg}", None

    def _reset_reply(self) -> tuple[str, None]:
        """Начинает новый раунд с пустым списком участников."""
        new_round_id = db.reset_round()
        return (
            f"✅ Розыгрыш сброшен. Новый раунд №{new_round_id} — "
            "участники с чистого листа."
        ), None

    def _winner_reply(self) -> tuple[str, None]:
        """Выбирает случайного победителя, если розыгрыш завершён."""
        round_id, ends_at = db.current_round()
        is_running = ends_at and ends_at > today_iso()
        if is_running:
            return (
                f"Розыгрыш ещё идёт до {ends_at}. "
                "Выбрать победителя можно после окончания."
            ), None
        winner = db.pick_winner(round_id)
        if not winner:
            return ("Участников пока нет — "
                    "победителя выбирать не из кого."), None
        name = winner[1] or "участник"  # имя могло не сохраниться
        return WINNER.format(name=name, uid=winner[0]), None


def today_iso() -> str:
    """Сегодняшняя дата ГГГГ-ММ-ДД (сравнивается с датой окончания раунда)."""
    return date.today().isoformat()
