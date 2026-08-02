from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from studytalk.db.models import Subject


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Minhas matérias", callback_data="menu:subjects"),
                InlineKeyboardButton(text="🎙️ Enviar áudio", callback_data="menu:send_audio"),
            ]
        ]
    )


def new_subject_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="+ Nova matéria", callback_data="subject:new")]
        ]
    )


def subjects_list_kb(subjects: list[Subject], *, for_linking: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for subject in subjects:
        prefix = "link" if for_linking else "subject:view"
        callback = f"link:{subject.id}" if for_linking else f"subject:view:{subject.id}"
        rows.append([InlineKeyboardButton(text=subject.name, callback_data=callback)])
    rows.append([InlineKeyboardButton(text="+ Nova matéria", callback_data="subject:new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
