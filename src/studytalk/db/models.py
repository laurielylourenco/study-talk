from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    subjects: Mapped[list["Subject"]] = relationship(back_populates="user")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_subject_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="subjects")
    lesson_notes: Mapped[list["LessonNote"]] = relationship(back_populates="subject")


class LessonNote(Base):
    __tablename__ = "lesson_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    user_audio_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    improved_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    subject: Mapped["Subject"] = relationship(back_populates="lesson_notes")
    review_sessions: Mapped[list["ReviewSession"]] = relationship(back_populates="lesson_note")


class ReviewSession(Base):
    """Schema criado na Meta 1; uso a partir da Meta 4."""

    __tablename__ = "review_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_note_id: Mapped[int] = mapped_column(ForeignKey("lesson_notes.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    user_audio_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lesson_note: Mapped["LessonNote"] = relationship(back_populates="review_sessions")
