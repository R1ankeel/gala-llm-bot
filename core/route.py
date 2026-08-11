"""Строгая адресация и роутинг сообщений чата.

Формат адресации СТРОГИЙ: "{ник_бота}, ..." в начале сообщения.
Никакой fuzzy-логики словоформ ("Анюта", "Ань") — это сознательно
вынесено в Этап 9, если понадобится.
"""

from dataclasses import dataclass

ACTION_ADDRESSED = "addressed"
ACTION_LOG_ONLY = "log_only"


@dataclass
class RouteDecision:
    action: str  # "addressed" | "log_only"
    stripped_text: str | None = None  # текст без "Ник, " префикса, если addressed


def parse_addressed_message(text: str, bot_username: str) -> RouteDecision:
    """Проверяет, адресовано ли сообщение боту, по строгому формату.

    text.strip() должен начинаться с "{bot_username}," (регистронезависимо);
    допускается 0-1 пробел после запятой перед остальным текстом.
    Если остаток после запятой начинается с пунктуации (двойная запятая,
    двоеточие и т.п.) — это похоже на опечатку, решаем log_only.

    Примеры:
      "Анька, привет как дела" -> addressed, "привет как дела"
      "анька,привет"           -> addressed, "привет"
      "Аньке привет"           -> log_only (нет запятой сразу после ника)
      "привет, Анька, как дела" -> log_only (ник не в начале)
      "Анька,,привет"          -> log_only (опечатка в формате)
      ""                       -> log_only
    """
    stripped = (text or "").strip()
    if not stripped:
        return RouteDecision(action=ACTION_LOG_ONLY)

    prefix = f"{bot_username},"
    if not stripped.lower().startswith(prefix.lower()):
        return RouteDecision(action=ACTION_LOG_ONLY)

    rest = stripped[len(prefix):]
    if rest.startswith(" "):
        rest = rest[1:]
    rest = rest.strip()
    if not rest:
        return RouteDecision(action=ACTION_LOG_ONLY)
    if rest[0] in ",.:;":
        return RouteDecision(action=ACTION_LOG_ONLY)

    return RouteDecision(action=ACTION_ADDRESSED, stripped_text=rest)


def should_ignore_message(username: str, bot_username: str, ignored_users: set[str]) -> bool:
    """True если username == bot_username (бот не отвечает сам себе) или
    username в ignored_users. Пустой сет в этом этапе — наполнение списка
    игнора это Этап 9, но параметр закладывается уже сейчас, чтобы не
    трогать сигнатуру потом."""
    return username == bot_username or username in ignored_users
