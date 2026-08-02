from aiogram.fsm.state import State, StatesGroup


class CreateSubject(StatesGroup):
    waiting_name = State()


class LinkNote(StatesGroup):
    """Guarda file_id pendente até o usuário escolher a matéria."""

    waiting_subject = State()
