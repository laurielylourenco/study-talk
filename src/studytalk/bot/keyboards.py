from datetime import date, datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from studytalk.db.models import Subject

BRAZIL_TZ = timezone(timedelta(hours=-3))


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Minhas matérias", callback_data="menu:subjects"),
                InlineKeyboardButton(text="🎙️ Enviar áudio", callback_data="menu:send_audio"),
            ],
            [
                InlineKeyboardButton(text="🔁 Revisar", callback_data="menu:review"),
            ],
        ]
    )


def new_subject_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="+ Nova matéria", callback_data="subject:new")]
        ]
    )


def days_list_kb(
    days: list[date],
    subject_id: int,
    next_offset: int,
    has_more: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for day in days:
        rows.append([
            InlineKeyboardButton(
                text=f"📅 {day.strftime('%d/%m/%Y')}",
                callback_data=f"note:day:{subject_id}:{day.isoformat()}",
            )
        ])
    footer: list[InlineKeyboardButton] = []
    if has_more:
        footer.append(InlineKeyboardButton(text="Ver mais ↓", callback_data=f"note:more:{subject_id}:{next_offset}"))
    footer.append(InlineKeyboardButton(text="← Matérias", callback_data="menu:subjects"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notes_of_day_kb(
    note_items: list[tuple[int, datetime]],
    subject_id: int,
    subject_name: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for note_id, local_dt in note_items:
        rows.append([
            InlineKeyboardButton(
                text=f"📄 {local_dt.strftime('%Hh%M')}",
                callback_data=f"note:read:{note_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text=f"← {subject_name}", callback_data=f"subject:view:{subject_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subjects_list_kb(subjects: list[Subject], *, for_linking: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for subject in subjects:
        prefix = "link" if for_linking else "subject:view"
        callback = f"link:{subject.id}" if for_linking else f"subject:view:{subject.id}"
        rows.append([InlineKeyboardButton(text=subject.name, callback_data=callback)])
    rows.append([InlineKeyboardButton(text="+ Nova matéria", callback_data="subject:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_feedback_kb(has_more: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_more:
        rows.append([InlineKeyboardButton(text="🔁 Continuar revisando", callback_data="menu:review")])
    rows.append([InlineKeyboardButton(text="🏠 Menu principal", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
