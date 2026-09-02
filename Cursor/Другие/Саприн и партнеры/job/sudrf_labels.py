"""Точные названия вкладок и столбцов сайтов судов (ГАС «Правосудие»).

Районный/городской: job/sudrf_tabs_rayon.md
Областной (апелляция): job/sudrf_tabs_oblsud.md

Не путать:
- райсуд, вкладка: «ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)»
- внутри неё: «ЖАЛОБА № 1*», «ДВИЖЕНИЕ ЖАЛОБЫ»
- облсуд: вкладки другие (нет «ОБЖАЛОВАНИЕ…», есть «РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ», «УЧАСТНИКИ»)
"""

from __future__ import annotations

# --- Вкладки навигации (районный суд) ---
TAB_DELO = "ДЕЛО"
TAB_MOVEMENT = "ДВИЖЕНИЕ ДЕЛА"
TAB_PARTIES = "СТОРОНЫ ПО ДЕЛУ (ТРЕТЬИ ЛИЦА)"
TAB_APPEAL = "ОБЖАЛОВАНИЕ РЕШЕНИЙ, ОПРЕДЕЛЕНИЙ (ПОСТ.)"
TAB_WRITS = "ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ"
TAB_ACTS = "СУДЕБНЫЕ АКТЫ"

RAYON_TABS = (
    TAB_DELO,
    TAB_MOVEMENT,
    TAB_PARTIES,
    TAB_APPEAL,
    TAB_WRITS,
    TAB_ACTS,
)

# Секции внутри вкладки обжалования (не название вкладки!)
SECTION_APPEAL_COMPLAINT_PREFIX = "ЖАЛОБА №"
SECTION_APPEAL_MOVEMENT = "ДВИЖЕНИЕ ЖАЛОБЫ"
SECTION_APPEAL_MOVEMENT_BANNER = "---=== ДВИЖЕНИЕ ЖАЛОБЫ ===---"

# Поля шапки жалобы
FIELD_APPEAL_TYPE = "Вид жалобы (представления)"
FIELD_APPEAL_APPLICANT = "Заявитель"
FIELD_APPEAL_HIGHER_COURT = "Вышестоящий суд"

# --- Столбцы «ДВИЖЕНИЕ ДЕЛА» ---
# ✓ = используем для триггеров / комментариев
COL_MOV_EVENT = "Наименование события"  # ✓ триггер
COL_MOV_DATE = "Дата"  # ✓ триггер
COL_MOV_TIME = "Время"  # ✓ коммент
COL_MOV_PLACE = "Место проведения"  # —
COL_MOV_RESULT = "Результат события"  # ✓ триггер
COL_MOV_BASIS = "Основание для выбранного результата события"  # ✓ триггер
COL_MOV_NOTE = "Примечание"  # —
COL_MOV_PUBLISHED = "Дата размещения"  # ✓ триггер / коммент

MOVEMENT_COLUMNS = (
    COL_MOV_EVENT,
    COL_MOV_DATE,
    COL_MOV_TIME,
    COL_MOV_PLACE,
    COL_MOV_RESULT,
    COL_MOV_BASIS,
    COL_MOV_NOTE,
    COL_MOV_PUBLISHED,
)

MOVEMENT_TRIGGER_COLUMNS = (
    COL_MOV_EVENT,
    COL_MOV_DATE,
    COL_MOV_TIME,
    COL_MOV_RESULT,
    COL_MOV_BASIS,
    COL_MOV_PUBLISHED,
)

# --- Столбцы «ДВИЖЕНИЕ ЖАЛОБЫ» внутри вкладки обжалования ---
COL_APPEAL_EVENT = "Событие"  # ✓ триггер
COL_APPEAL_DATE = "Дата"  # ✓ триггер
COL_APPEAL_RESULT = "Результат"  # ✓ триггер
COL_APPEAL_BASIS = "Основание для выбранного результата"  # ✓ триггер
COL_APPEAL_NOTE = "Примечание"  # —
COL_APPEAL_PUBLISHED = "Дата размещения"  # ✓ триггер / коммент

# Ключевое поле/строка итога апелляции (ТЗ §1.7)
APPEAL_RESULT_LABEL = "Результат обжалования"

# События «ДВИЖЕНИЕ ЖАЛОБЫ» (скрины 2-1440/2026 и 2-6720/2025)
APPEAL_EVENT_REGISTER = "Регистрация жалобы (представления) в суде"
APPEAL_EVENT_SENT_UP = "Направлено в вышестоящую инстанцию"
APPEAL_EVENT_ACCEPT_DECISION = "Решение вопроса о принятии жалобы (представления) к рассмотрению"
APPEAL_RESULT_RETURNED = "Жалоба (предст.) ВОЗВРАЩЕНА"
APPEAL_BASIS_NONCOMPLIANCE = "НЕСООТВЕТСТВИЕ ТРЕБОВАНИЯМ"

APPEAL_MOVEMENT_COLUMNS = (
    COL_APPEAL_EVENT,
    COL_APPEAL_DATE,
    COL_APPEAL_RESULT,
    COL_APPEAL_BASIS,
    COL_APPEAL_NOTE,
    COL_APPEAL_PUBLISHED,
)

APPEAL_MOVEMENT_TRIGGER_COLUMNS = (
    COL_APPEAL_EVENT,
    COL_APPEAL_DATE,
    COL_APPEAL_RESULT,
    COL_APPEAL_BASIS,
    COL_APPEAL_PUBLISHED,
)

# --- Столбцы «ИСПОЛНИТЕЛЬНЫЕ ЛИСТЫ» ---
COL_WRIT_ISSUE_DATE = "Дата выдачи"  # ✓ триггер
COL_WRIT_BLANK = "Серия, номер бланка"  # ✓ коммент
COL_WRIT_EID = "Номер электронного ИД"  # ✓ коммент
COL_WRIT_STATUS = "Статус"  # ✓ триггер
COL_WRIT_TO = "Кому выдан / направлен"  # ✓ коммент

WRIT_COLUMNS = (
    COL_WRIT_ISSUE_DATE,
    COL_WRIT_BLANK,
    COL_WRIT_EID,
    COL_WRIT_STATUS,
    COL_WRIT_TO,
)

WRIT_TRIGGER_COLUMNS = (
    COL_WRIT_ISSUE_DATE,
    COL_WRIT_STATUS,
)


def _up(s: str) -> str:
    return " ".join(str(s or "").upper().replace("Ё", "Е").split())


def is_rayon_appeal_tab(name: str) -> bool:
    """Вкладка обжалования райсуда или внутренние секции жалобы."""
    u = _up(name)
    if _up(TAB_APPEAL) in u or "ОБЖАЛОВАНИЕ РЕШЕНИЙ" in u:
        return True
    if SECTION_APPEAL_COMPLAINT_PREFIX in u or "ДВИЖЕНИЕ ЖАЛОБЫ" in u:
        return True
    return False


def is_rayon_appeal_movement_section(name: str) -> bool:
    """Секция/вкладка, где лежат строки «ДВИЖЕНИЕ ЖАЛОБЫ»."""
    u = _up(name)
    if "ДВИЖЕНИЕ ЖАЛОБЫ" in u:
        return True
    if _up(TAB_APPEAL) in u or "ОБЖАЛОВАНИЕ РЕШЕНИЙ" in u:
        return True
    return False


def is_rayon_writs_tab(name: str) -> bool:
    u = _up(name)
    return _up(TAB_WRITS) in u or ("ИСПОЛНИТЕЛЬН" in u and "ЛИСТ" in u)


def is_rayon_movement_tab(name: str) -> bool:
    u = _up(name)
    return _up(TAB_MOVEMENT) in u


def is_rayon_acts_tab(name: str) -> bool:
    return _up(TAB_ACTS) in _up(name)


# =============================================================================
# Областной суд (апелляция) — скрин 33-5260/2025
# =============================================================================

OBLSUD_TAB_DELO = "ДЕЛО"
OBLSUD_TAB_LOWER_COURT = "РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ"
OBLSUD_TAB_MOVEMENT = "ДВИЖЕНИЕ ДЕЛА"
OBLSUD_TAB_PARTICIPANTS = "УЧАСТНИКИ"  # не «СТОРОНЫ ПО ДЕЛУ…»
OBLSUD_TAB_ACTS = "СУДЕБНЫЕ АКТЫ"

OBLSUD_TABS = (
    OBLSUD_TAB_DELO,
    OBLSUD_TAB_LOWER_COURT,
    OBLSUD_TAB_MOVEMENT,
    OBLSUD_TAB_PARTICIPANTS,
    OBLSUD_TAB_ACTS,
)

# Поля вкладки «РАССМОТРЕНИЕ В НИЖЕСТОЯЩЕМ СУДЕ»
OBLSUD_FIELD_LOWER_COURT_NAME = "Суд (судебный участок) первой инстанции"
OBLSUD_FIELD_LOWER_CASE_NUMBER = "Номер дела в первой инстанции"
OBLSUD_FIELD_LOWER_JUDGE = "Судья (мировой судья) первой инстанции"


def is_oblsud_lower_court_tab(name: str) -> bool:
    u = _up(name)
    return _up(OBLSUD_TAB_LOWER_COURT) in u or "НИЖЕСТОЯЩЕМ СУДЕ" in u


def is_oblsud_participants_tab(name: str) -> bool:
    return _up(OBLSUD_TAB_PARTICIPANTS) in _up(name)


def is_oblsud_movement_tab(name: str) -> bool:
    return _up(OBLSUD_TAB_MOVEMENT) in _up(name)


# 6 районных судов г. Воронежа (не область, не облсуд)
VORONEZH_CITY_RAYON_HOSTS = (
    "sovetsky--vrn.sudrf.ru",
    "kominternovsky--vrn.sudrf.ru",
    "zheleznodorozhny--vrn.sudrf.ru",
    "levoberezhny--vrn.sudrf.ru",
    "centralny--vrn.sudrf.ru",
    "lensud--vrn.sudrf.ru",
)
