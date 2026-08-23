from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Minhas matérias", callback_data="menu:subjects")],
            [InlineKeyboardButton(text="🎤 Enviar áudio de estudo", callback_data="menu:audio")],
            [InlineKeyboardButton(text="📖 Revisar", callback_data="menu:review")],
        ]
    )


def new_subject_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Criar matéria", callback_data="subject:new")],
            [InlineKeyboardButton(text="🏠 Menu principal", callback_data="menu:home")],
        ]
    )


def subjects_list_kb(subjects, *, for_linking: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for s in subjects:
        data = f"link:{s.id}" if for_linking else f"subject:view:{s.id}"
        rows.append([InlineKeyboardButton(text=s.name, callback_data=data)])
    rows.append([InlineKeyboardButton(text="🏠 Menu principal", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def days_list_kb(days, *, subject_id: int, next_offset: int, has_more: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📅 {day.strftime('%d/%m/%Y')}",
                callback_data=f"note:day:{subject_id}:{day.isoformat()}",
            )
        ]
        for day in days
    ]
    footer = []
    if has_more:
        footer.append(
            InlineKeyboardButton(
                text="Ver mais ↓",
                callback_data=f"note:more:{subject_id}:{next_offset}",
            )
        )
    footer.append(InlineKeyboardButton(text="← Matérias", callback_data="menu:subjects"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notes_of_day_kb(note_items, *, subject_id: int, subject_name: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"📄 {local_dt.strftime('%Hh%M')}",
                callback_data=f"note:read:{note_id}",
            )
        ]
        for note_id, local_dt in note_items
    ]
    rows.append(
        [InlineKeyboardButton(text=f"← {subject_name}", callback_data=f"subject:view:{subject_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_feedback_kb(*, has_more: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_more:
        rows.append([InlineKeyboardButton(text="▶️ Próxima matéria", callback_data="menu:review")])
    rows.append([InlineKeyboardButton(text="🏠 Menu principal", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def review_in_session_kb() -> InlineKeyboardMarkup:
    """Teclado exibido durante a sessão de revisão multi-turn (junto com cada pergunta)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭ Pular pergunta", callback_data="review:skip"),
                InlineKeyboardButton(text="🛑 Encerrar revisão", callback_data="review:end_session"),
            ]
        ]
    )


def post_review_kb(*, has_more: bool, subject_id: int) -> InlineKeyboardMarkup:
    """Teclado exibido ao encerrar uma sessão de revisão."""
    rows = []
    if has_more:
        rows.append([
            InlineKeyboardButton(text="▶️ Próxima matéria", callback_data="menu:review"),
        ])
    rows.append([
        InlineKeyboardButton(text="📖 Rever notas", callback_data=f"subject:view:{subject_id}"),
        InlineKeyboardButton(text="🏠 Menu principal", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
