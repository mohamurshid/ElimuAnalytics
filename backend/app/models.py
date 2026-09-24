"""
Database schema, as designed in Chapter 4 section 4.4.1.

Eleven tables: SCHOOL, TEACHER, CLASSROOM, STUDENT, STRAND, ITEM, RESPONSE,
ABILITY_SCORE, GAP_FLAG, REPORT, CURRICULUM_CHUNK.

Two design points carried over from Phase 0 rather than re-decided here:

  * RESPONSE.correctness is stored as a boolean because that is the domain
    truth, and converted to integer 0/1 at the point of building the response
    matrix. girth rejects booleans (Day 1), so the conversion lives in the
    repository, not in the schema.
  * CURRICULUM_CHUNK.embedding is a 384-dimension vector because that is the
    output width of all-MiniLM-L6-v2. Changing embedding model means changing
    this number and re-embedding the corpus.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    # sqlalchemy.Uuid renders as PostgreSQL UUID in production and as a portable
    # type elsewhere, so the repository can be tested without a live Postgres.
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class School(Base):
    __tablename__ = "school"

    school_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # public / private

    teachers: Mapped[list[Teacher]] = relationship(back_populates="school")
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="school")


class Teacher(Base):
    __tablename__ = "teacher"
    __table_args__ = (UniqueConstraint("email", name="uq_teacher_email"),)

    teacher_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # teacher | school_admin | system_admin (Chapter 3, five core modules)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="teacher")
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.school_id", ondelete="CASCADE"), nullable=False
    )

    school: Mapped[School] = relationship(back_populates="teachers")
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="teacher")


class Classroom(Base):
    __tablename__ = "classroom"

    class_id: Mapped[uuid.UUID] = _pk()
    grade: Mapped[str] = mapped_column(String(20), nullable=False)  # "Grade 5"
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.school_id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teacher.teacher_id", ondelete="SET NULL"), nullable=True
    )

    school: Mapped[School] = relationship(back_populates="classrooms")
    teacher: Mapped[Teacher] = relationship(back_populates="classrooms")
    students: Mapped[list[Student]] = relationship(back_populates="classroom")


class Student(Base):
    __tablename__ = "student"

    student_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.class_id", ondelete="CASCADE"), nullable=False
    )

    classroom: Mapped[Classroom] = relationship(back_populates="students")
    responses: Mapped[list[Response]] = relationship(back_populates="student")


class Strand(Base):
    __tablename__ = "strand"

    strand_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    level: Mapped[str] = mapped_column(String(50), nullable=False)  # Lower / Upper Primary

    items: Mapped[list[Item]] = relationship(back_populates="strand")


class Item(Base):
    __tablename__ = "item"

    item_id: Mapped[uuid.UUID] = _pk()
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Null until the strand has been calibrated.
    difficulty_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    discrimination_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Retiring an item must not delete the responses learners already gave to
    # it: that would silently change every ability estimate ever computed from
    # them. Withdrawn items are deactivated, and calibration ignores them.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                            server_default="true")

    strand: Mapped[Strand] = relationship(back_populates="items")
    responses: Mapped[list[Response]] = relationship(back_populates="item")


class Response(Base):
    __tablename__ = "response"

    response_id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("item.item_id", ondelete="CASCADE"), nullable=False
    )
    correctness: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    student: Mapped[Student] = relationship(back_populates="responses")
    item: Mapped[Item] = relationship(back_populates="responses")


class AbilityScore(Base):
    __tablename__ = "ability_score"

    score_id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), nullable=False
    )
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    # How many items this estimate rests on. The Day 3 minimum-responses rule
    # cannot be enforced downstream without it.
    items_answered: Mapped[int] = mapped_column(nullable=False, default=0)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GapFlag(Base):
    __tablename__ = "gap_flag"

    flag_id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Report(Base):
    __tablename__ = "report"

    report_id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    content_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sw: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CurriculumChunk(Base):
    __tablename__ = "curriculum_chunk"

    chunk_id: Mapped[uuid.UUID] = _pk()
    strand_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="SET NULL"), nullable=True
    )
    # Retrieval filters on these before embedding similarity is considered.
    # Measured at full corpus scale: realistic queries reach 64.3% top-1 without
    # the filter and 100% with it, because 26% of KICD sub-strand titles repeat
    # across grades - the distinguishing information is metadata, not text.
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    learning_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sub_strand: Mapped[str | None] = mapped_column(String(500), nullable=True)
    syllabus_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
