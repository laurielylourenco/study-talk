from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    review_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    subjects: Mapped[list["Subject"]] = relationship(back_populates="user")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_subject_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="subjects")
    lesson_notes: Mapped[list["LessonNote"]] = relationship(back_populates="subject")
    review_sessions: Mapped[list["ReviewSession"]] = relationship(back_populates="subject")
    knowledge: Mapped["SubjectKnowledge | None"] = relationship(back_populates="subject")
    questions: Mapped[list["Question"]] = relationship(back_populates="subject")


class LessonNote(Base):
    __tablename__ = "lesson_notes"
    __table_args__ = (
        CheckConstraint("student_clarity_score BETWEEN 0 AND 3", name="ck_ln_clarity_score"),
        CheckConstraint(
            "knowledge_type IN ('novo', 'revisão', 'aprofundamento', 'aplicação')",
            name="ck_ln_knowledge_type",
        ),
        Index("ix_lesson_notes_subject_lesson", "subject_id", "lesson_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    user_audio_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    improved_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Novos campos
    lesson_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    student_clarity_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    structured_concepts: Mapped[str | None] = mapped_column(Text, nullable=True)
    knowledge_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    subject: Mapped["Subject"] = relationship(back_populates="lesson_notes")
    questions: Mapped[list["Question"]] = relationship(back_populates="lesson_note")


class SubjectKnowledge(Base):
    """Mapa acumulado de conhecimento de uma disciplina, atualizado a cada aula."""

    __tablename__ = "subject_knowledge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"), unique=True, nullable=False
    )
    knowledge_map: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_lesson_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    subject: Mapped["Subject"] = relationship(back_populates="knowledge")


class Question(Base):
    """Banco de perguntas geradas por aula."""

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "bloom_type IN ('memorização','compreensão','aplicação','raciocínio',"
            "'identificação_de_erros','conexão')",
            name="ck_q_bloom_type",
        ),
        CheckConstraint(
            "difficulty IN ('fácil','médio','difícil')",
            name="ck_q_difficulty",
        ),
        CheckConstraint("times_asked >= 0", name="ck_q_times_asked_nn"),
        CheckConstraint("times_correct >= 0", name="ck_q_times_correct_nn"),
        CheckConstraint("times_correct <= times_asked", name="ck_q_correct_lte_asked"),
        Index("ix_questions_subject_bloom", "subject_id", "bloom_type"),
        Index("ix_questions_subject_concept", "subject_id", "target_concept"),
        Index("ix_questions_subject_difficulty", "subject_id", "difficulty"),
        Index("ix_questions_last_asked", "subject_id", "last_asked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    lesson_note_id: Mapped[int] = mapped_column(ForeignKey("lesson_notes.id"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    bloom_type: Mapped[str] = mapped_column(String(30), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False)
    target_concept: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    times_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    times_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subject: Mapped["Subject"] = relationship(back_populates="questions")
    lesson_note: Mapped["LessonNote"] = relationship(back_populates="questions")
    review_sessions: Mapped[list["ReviewSession"]] = relationship(back_populates="question")


class ReviewSession(Base):
    """Sessão de revisão."""

    __tablename__ = "review_sessions"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 3", name="ck_rs_score"),
        Index("ix_review_sessions_subject_reviewed", "subject_id", "reviewed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id"), nullable=True
    )
    question_text_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_audio_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criteria_evaluation: Mapped[str | None] = mapped_column(Text, nullable=True)
    identified_gaps: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action_taken: Mapped[str | None] = mapped_column(String(50), nullable=True)
    history_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    subject: Mapped["Subject"] = relationship(back_populates="review_sessions")
    question: Mapped["Question | None"] = relationship(back_populates="review_sessions")
