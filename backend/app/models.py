"""
Database schema, as designed in Chapter 4 section 4.4.1.

Eleven tables as designed: SCHOOL, TEACHER, CLASSROOM, STUDENT, STRAND, ITEM,
RESPONSE, ABILITY_SCORE, GAP_FLAG, REPORT, CURRICULUM_CHUNK - plus
ASSESSMENT_BATCH, which the diagram does not contain and offline submission
requires (see its docstring).

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
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
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
    # Not in the Chapter 4 diagram. Most primary schools run more than one
    # stream per grade, and grade alone cannot tell them apart - "Grade 5 Blue"
    # and "Grade 5 Green" would be the same row.
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=""
    )
    # A classroom that has ever held learners is deactivated rather than
    # deleted, for the same reason an answered item is: the cascade would
    # reach their responses and silently change other learners' estimates.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("school.school_id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teacher.teacher_id", ondelete="SET NULL"), nullable=True
    )

    school: Mapped[School] = relationship(back_populates="classrooms")
    teacher: Mapped[Teacher] = relationship(back_populates="classrooms")
    students: Mapped[list[Student]] = relationship(back_populates="classroom")


class ClassStrand(Base):
    """Which strands a class is assessed on.

    Removing a strand from a class deletes only this row. Answers, levels and
    flags belong to learners and strands, not to the link, so they stay - and
    adding the strand back brings them back into view.
    """

    __tablename__ = "class_strand"

    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.class_id", ondelete="CASCADE"), primary_key=True
    )
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Student(Base):
    __tablename__ = "student"

    student_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.class_id", ondelete="CASCADE"), nullable=False
    )
    # A learner who has answered anything is withdrawn, never deleted. Deleting
    # cascades to their responses, and every item they answered is recalibrated
    # without them - which moves other learners' ability estimates.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Set when this learner was deactivated *by* their classroom being
    # withdrawn, rather than individually.
    #
    # Without it, restoring a classroom cannot be done correctly: reactivating
    # every learner in it would also undo withdrawals a teacher made
    # deliberately beforehand, and reactivating none would make the restore
    # useless. The flag records which of the two happened, so the undo
    # reverses exactly what the action did.
    withdrawn_with_class: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    classroom: Mapped[Classroom] = relationship(back_populates="students")
    responses: Mapped[list[Response]] = relationship(back_populates="student")


class Strand(Base):
    __tablename__ = "strand"

    strand_id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    level: Mapped[str] = mapped_column(String(50), nullable=False)  # Lower / Upper Primary
    # Which KICD learning area this strand belongs to - "Science and
    # Technology", "Mathematics", "Kiswahili". Must match the spelling in
    # curriculum_chunk.learning_area, because curriculum retrieval filters on
    # grade AND learning area before similarity is considered, and that filter
    # is not an optimisation: on realistic queries, unfiltered top-1 over the
    # whole corpus was 64.3% against 100% filtered (14 queries - small, and
    # the figure belongs with its n). A strand named "Reading" exists in four
    # language
    # designs across six grades, so without this the pre-filter would be
    # guessing among them.
    #
    # Nullable because a strand can exist before anyone has said where it
    # belongs. Report generation then refuses with a clear message rather than
    # retrieving against a guess.
    learning_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # The grade whose curriculum design this sub-strand comes from - which is
    # not always the grade of the class assessed on it: a Grade 5 class can be
    # assessed on a Grade 4 sub-strand on purpose, to find where a gap began.
    # Report retrieval filters on THIS grade, so remediation is grounded in the
    # curriculum the learner is actually being tested against.
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The catalogue key ("Grade 5|Science and Technology|3.0|3.3", see
    # catalogue.py). Unique: strands are shared across schools, like the
    # question bank, so the first class to pick a sub-strand creates its row
    # and every later class reuses it - and its questions, and their
    # calibration. Nullable for strands made before the catalogue existed.
    curriculum_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, unique=True
    )

    items: Mapped[list[Item]] = relationship(back_populates="strand")


class Item(Base):
    __tablename__ = "item"

    item_id: Mapped[uuid.UUID] = _pk()
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Answer options and the key, for items a learner answers on a device.
    #
    # Both are nullable on purpose. An item with only question text is still a
    # valid item - a teacher can ask it aloud or on paper and record the
    # result - it simply cannot be delivered to a learner, because nothing
    # knows what the right answer is. The two modes coexist rather than one
    # replacing the other.
    #
    # `correct_option` must never reach a learner's device. The delivery
    # endpoint has its own schema that does not contain this field, and
    # correctness is computed on the server from the option a learner chose.
    # A client that reports its own correctness can report whatever it likes.
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    correct_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # Which option the learner chose, when they chose one on a device. Null
    # for responses a teacher marked, where no option was recorded.
    #
    # Not needed to compute ability - correctness is - but kept because which
    # wrong answer a learner picked is the evidence behind distractor
    # analysis, and that evidence cannot be recovered after the fact.
    selected_option: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nullable: responses seeded for demonstration, and those recorded before
    # batching existed, belong to no submission.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessment_batch.batch_id", ondelete="SET NULL"), nullable=True
    )
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


class RefreshToken(Base):
    """A long-lived credential that buys short-lived access tokens.

    Not in the Chapter 4 diagram. It exists because the browser holds the
    access token in memory only - a deliberate choice, since anything in
    `localStorage` is readable by any script that gets injected into the page -
    and memory does not survive a page reload. Without this, every refresh
    would sign a teacher out.

    Three decisions worth defending:

    **The token is opaque, not a JWT.** A JWT is valid until it expires and
    cannot be withdrawn. A stored token can be revoked the moment a teacher
    logs out or a theft is suspected, which is the entire point of separating
    it from the access token.

    **Only a SHA-256 hash is stored.** A database disclosure then yields
    nothing usable. bcrypt is unnecessary here and would be worse: the token
    is 256 bits of randomness rather than a guessable password, and hashing
    must be fast enough to look up by index on every refresh.

    **Tokens are grouped into a family and rotated.** Each refresh issues a
    new token and retires the old one. If a retired token is ever presented
    again, either the legitimate client replayed it or someone stole it - and
    the server cannot tell which. The safe response is to revoke the whole
    family, forcing a fresh sign-in.
    """

    __tablename__ = "refresh_token"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_refresh_token_hash"),)

    token_id: Mapped[uuid.UUID] = _pk()
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teacher.teacher_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Every token descended from one sign-in shares a family id.
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    teacher: Mapped[Teacher] = relationship()


class AssessmentBatch(Base):
    """One submission of learner responses, from one device, at one moment.

    Not in the Chapter 4 diagram. It exists for idempotency: a tablet that
    submits offline work and loses the connection before seeing a reply will
    retry, and without a key to recognise the retry by, the same responses are
    recorded twice. A duplicated response is not a visible error - it silently
    overwrites a cell in the response matrix and moves ability estimates.

    `client_batch_id` is generated on the device, not here, because the server
    cannot tell two identical submissions apart after the fact. It is unique,
    so the retry is recognised by the database rather than by a race-prone
    check in application code.
    """

    __tablename__ = "assessment_batch"
    __table_args__ = (
        UniqueConstraint("client_batch_id", name="uq_assessment_batch_client_id"),
    )

    batch_id: Mapped[uuid.UUID] = _pk()
    client_batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classroom.class_id", ondelete="CASCADE"), nullable=False
    )
    strand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teacher.teacher_id", ondelete="SET NULL"), nullable=True
    )
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[datetime] = mapped_column(
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
    """A generated diagnostic report, and the evidence that it was grounded.

    Everything after `pdf_url` exists so that a report can be audited after it
    was sent. A generated report is a claim about a child, and the claim is
    only as good as the curriculum text it was built from - so what was
    retrieved, how close it scored, which model wrote it and what the grounding
    check concluded are all stored alongside the text rather than left in a log.

    `exportable` is stored rather than derived at read time. A report is
    exportable only when the grounding check verified a verbatim citation
    against the retrieved curriculum and found nothing fabricated; a failed
    report is kept and shown to the teacher, marked, but cannot be printed or
    sent home. Recomputing that at every read would mean the answer could
    change under an unrelated code edit, after a teacher had already been told
    the report was fit to send.

    Note what does NOT block export: vague-phrase detection. That list is a
    heuristic, and its Kiswahili half is not yet validated by a Kiswahili
    speaker, so a wrong entry would block a perfectly good report. Vague
    phrases are recorded and shown; they never decide.
    """

    __tablename__ = "report"

    report_id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student.student_id", ondelete="CASCADE"), nullable=False
    )
    # A report is about one learner in one strand. Without this, two reports on
    # the same learner for different strands are indistinguishable.
    strand_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="SET NULL"), nullable=True
    )
    content_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sw: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- grounding evidence ---
    # GROUNDED | WEAK | FABRICATED, from grounding.check().
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exportable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # The full check output, so a verdict can be re-examined without rerunning
    # the model: which quotations were verified, which were not, what vague
    # phrases appeared, lexical overlap with the supplied context.
    grounding: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- what it was built from ---
    # Cosine similarity of the best retrieved chunk. A weak best match does not
    # block generation - the prompt already instructs the model to refuse when
    # the curriculum does not cover the sub-strand, and it does - but it is
    # recorded so a weakly grounded report is identifiable afterwards instead
    # of looking the same as a strong one.
    top_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # curriculum_chunk.source_row values, which are unique and trace back to
    # the exact records in the harvested JSON.
    chunk_source_rows: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    # --- how it was generated ---
    # Recorded per report because they change. The September spike ran on
    # claude-sonnet-4-5, which retires on 30 Nov 2026; a report carrying no
    # model name cannot be interpreted a year later.
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Of the billed output tokens, how many were internal reasoning. Measured
    # at 60% of output in the 14 Oct spike run, at the lowest effort setting,
    # and it cannot be switched off on these models - so it is a cost driver
    # worth being able to total up rather than estimate.
    thinking_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- how far it got ---
    # pending | ready | failed. The row is created before the content exists,
    # because generation takes about half a minute and the request that asks
    # for it cannot be held open that long - 32 to 38 seconds, measured, was
    # already past what the development proxy would wait, and a mobile
    # network is not more patient than a proxy.
    #
    # Derived state would not do. "content_en IS NULL" cannot tell a report
    # that is still running from one where the model returned nothing, and the
    # second is a real outcome with a test of its own.
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", server_default="pending"
    )
    # Why a failed report failed, in a sentence a teacher can read. Without
    # it a failure is a blank row and the only account of it is a server log
    # that no teacher will ever see.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Wall clock for the generation itself. Recorded because it turned out to
    # matter as much as the cost: a report slow enough for something in front
    # of it to give up is indistinguishable, from the browser, from a crash.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # When the report was REQUESTED, not finished - the row now exists before
    # its content does. Completion is this plus duration_ms.
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CurriculumChunk(Base):
    __tablename__ = "curriculum_chunk"

    chunk_id: Mapped[uuid.UUID] = _pk()
    # Left NULL by ingest. The `strand` rows are assessment strands, seeded
    # independently, and they do not correspond one-to-one with the curriculum
    # strand strings in the KICD corpus. Retrieval never filters on this.
    strand_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strand.strand_id", ondelete="SET NULL"), nullable=True
    )
    # Provenance, and deliberately NOT unique. The harvested id is built from
    # the grade plus the subject slugged to eight characters, so CRE, IRE and
    # HRE all become "religiou" and Arabic, French and Mandarin all become
    # "foreignl": 162 ids are shared by 213 rows of different content. Anything
    # that treats this as a key loses data. `source_row` is the record's index
    # in the harvested JSON, which is unique, and is what traces a chunk back.
    source_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Retrieval filters on grade and learning_area BEFORE embedding similarity
    # is considered, and the filter is not an optimisation - it is the only
    # reason retrieval works.
    #
    # Measured 17 October against the corpus as it is actually embedded: the
    # curriculum head, not the whole chunk. Two tests, which must not be
    # mixed - doing so is how this comment carried a wrong figure for a day:
    #
    #   * 300 heading queries over all 1,617 chunks - top-1 46.3%, top-5
    #     72.0%, MRR 0.577, mean top1-top2 margin 0.042. The margin is the
    #     real finding: the leading candidates are effectively tied, so
    #     retrieval on wording alone is guessing. This test has no filtered
    #     counterpart.
    #   * 14 realistic queries, teacher phrasing and failed items with
    #     curriculum vocabulary deliberately avoided - top-1 64.3% over the
    #     whole corpus against 100% with grade and learning area applied
    #     first, which cuts the candidates to 8. Fourteen queries is a small
    #     sample; quote it with its n.
    #
    # Weakest areas on the 300-query test, where sub-strand wording repeats
    # across the six grades: Indigenous Language 16%, Kiswahili 23%,
    # Mathematics 25%, English 33%.
    #
    # `strand` and `sub_strand` are stored for display and citation only. They
    # are not join keys: the extractor let content lists bleed into sub_strand
    # ("3.3 Heat transfer   Modes of heat transfer in nature  ...") and OCR
    # splits words in strand ("Living things and their Environme nt"), so
    # neither is reliable enough to match on.
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    learning_area: Mapped[str | None] = mapped_column(String(80), nullable=True)
    strand: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sub_strand: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lessons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Repaired by curriculum.normalise() on the way in, never on the way out.
    # The report prompt quotes this text verbatim, so what is stored has to be
    # exactly what a teacher reads - otherwise a rendered quotation stops
    # matching the chunk and the grounding check calls it fabricated.
    syllabus_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Unit vectors, so cosine distance and a dot product agree.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
