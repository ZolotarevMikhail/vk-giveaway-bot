"""База данных розыгрыша (SQLite). Ничего не теряется: участники,
обязательные сообщества и раунды хранятся в файле giveaway.db."""

import random
import sqlite3
from datetime import datetime

DB_FILE = "giveaway.db"

# Формат отметок времени в базе: секунды, без микросекунд
TIME_FORMAT = dict(timespec="seconds")


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    """Текущий момент в едином формате для всех записей базы."""
    return datetime.now().isoformat(**TIME_FORMAT)


def init_db():
    """Создаёт таблицы, если их ещё нет."""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS required_groups (
                screen_name TEXT PRIMARY KEY,
                added_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rounds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ends_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS participants (
                round_id   INTEGER NOT NULL REFERENCES rounds(id),
                user_id    INTEGER NOT NULL,
                first_name TEXT,
                joined_at  TEXT NOT NULL,
                PRIMARY KEY (round_id, user_id)
            );
            """
        )
        # Раунд по умолчанию: создаём первый, если таблица пуста
        if not conn.execute("SELECT 1 FROM rounds LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO rounds (started_at) VALUES (?)",
                (_now(),),
            )


# ---------- Сообщества ----------

def list_groups() -> list[str]:
    """Короткие имена всех обязательных сообществ по алфавиту."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT screen_name FROM required_groups ORDER BY screen_name"
        ).fetchall()
    return [row[0] for row in rows]


def add_group(screen_name: str) -> bool:
    """True — добавлено, False — уже было."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO required_groups (screen_name, added_at) "
            "VALUES (?, ?)",
            (screen_name, _now()),
        )
    return cursor.rowcount > 0


def remove_group(screen_name: str) -> bool:
    """True — удалено, False — не было в списке."""
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM required_groups WHERE screen_name = ?", (screen_name,)
        )
    return cursor.rowcount > 0


# ---------- Раунд ----------

def current_round() -> tuple[int, str | None]:
    """(id последнего раунда, дата окончания или None)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, ends_at FROM rounds ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return (row[0], row[1]) if row else (0, None)


def reset_round() -> int:
    """Сброс: создаёт новый раунд, участники старого остаются в истории."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO rounds (started_at) VALUES (?)",
            (_now(),),
        )
    return cursor.lastrowid


def set_end_date(ends_at: str) -> None:
    """Записывает дату окончания в последний раунд."""
    with _connect() as conn:
        round_id, _ = current_round()
        conn.execute(
            "UPDATE rounds SET ends_at = ? WHERE id = ?", (ends_at, round_id)
        )


# ---------- Участники ----------

def add_participant(round_id: int, user_id: int, first_name: str) -> bool:
    """True — участие принято, False — уже участвует (защита от повторов).

    Проверка на дубли лежит на составном ключе (round_id, user_id):
    повторная запись просто игнорируется.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO participants "
            "(round_id, user_id, first_name, joined_at) VALUES (?, ?, ?, ?)",
            (round_id, user_id, first_name, _now()),
        )
    return cursor.rowcount > 0


def participants(round_id: int) -> list[tuple[int, str]]:
    """(user_id, имя) всех участников раунда — в порядке вступления."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, first_name FROM participants WHERE round_id = ?"
            " ORDER BY joined_at",
            (round_id,),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def pick_winner(round_id: int) -> tuple[int, str] | None:
    """Случайный победитель из участников раунда (None — если список пуст)."""
    candidates = participants(round_id)
    return random.choice(candidates) if candidates else None
