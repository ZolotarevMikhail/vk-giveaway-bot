"""Локальный тест без ВКонтакте: проверяет базу данных и админ-команды.
Запуск:  python3 test_local.py
"""

import os
import sqlite3
import sys

# Тестовый .env-набор, чтобы не трогать реальный .env
os.environ["ADMIN_IDS"] = "777"

import giveaway_db as db  # noqa: E402
from bot import GiveawayBot  # noqa: E402

DB = "test_giveaway.db"
db.DB_FILE = DB
if os.path.exists(DB):
    os.remove(DB)
db.init_db()


class FakeVk:
    """Стойка-обманка вместо настоящей связи с ВК."""

    def __init__(self, subscribers=(1, 2)):
        self.subscribers = set(subscribers)

    async def is_member(self, group, user_id):
        return user_id in self.subscribers

    async def group_title(self, group):
        return f"[{group}]"

    async def _call(self, method, **params):
        if method == "users.get":
            return [{"first_name": "Тест"}]
        return None


async def run_tests():
    bot = GiveawayBot(FakeVk())
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("✅" if cond else "❌"), name)
        ok = ok and cond

    # 1. Участие
    text, kb = await bot.handle(1, "Участвовать")
    check("Участие принято (нет обязательных сообществ)", "Ты в игре" in text)

    # 2. Защита от повторов
    text, _ = await bot.handle(1, "Участвовать")
    check("Повторное участие отклонено", "уже участвуешь" in text)

    # 3. Обязательные сообщества: подписанный проходит, нет — нет
    db.add_group("club_test")
    text, _ = await bot.handle(2, "Участвовать")
    check("Подписанный на сообщество участвует", "Ты в игре" in text)
    text, _ = await bot.handle(3, "Участвовать")
    check("Неподписанный получает отказ с названием сообщества", "подписан" in text)

    # 4. Участники не теряются
    rid, _ = db.current_round()
    check("В базе 2 участника", len(db.participants(rid)) == 2)

    # 5. Победитель
    text, _ = await bot.handle(777, "/победитель")
    check("Победитель выбран и есть ссылка", "vk.com/id" in text)

    # 6. Сброс
    text, _ = await bot.handle(777, "/сброс")
    new_rid, _ = db.current_round()
    check("Сброс создаёт новый пустой раунд", "сброшен" in text and not db.participants(new_rid))

    # 7. Сообщества: добавить/список/удалить
    await bot.handle(777, "/добавить vk.com/new_club")
    check("Ссылка превращается в короткое имя", "new_club" in db.list_groups())
    text, _ = await bot.handle(777, "/удалить new_club")
    check("Удаление сообщества", "new_club" not in db.list_groups())

    # 8. Дата окончания и статус
    await bot.handle(777, "/конец 2099-12-31")
    text, _ = await bot.handle(777, "/статус")
    check("Статус показывает дату окончания", "2099-12-31" in text)
    text, _ = await bot.handle(777, "/победитель")
    check("До окончания победителя не выбирает", "ещё идёт" in text)

    # 9. Не-админ не может управлять
    rid_before, _ = db.current_round()
    text, _ = await bot.handle(555, "/сброс")
    rid_after, _ = db.current_round()
    check("Не-админ не сбрасывает раунд", rid_before == rid_after)

    os.remove(DB)
    print("\n" + ("ВСЕ ТЕСТЫ ПРОШЛИ ✅" if ok else "ЕСТЬ ОШИБКИ ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(__import__("asyncio").run(run_tests()))