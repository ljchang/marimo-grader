"""SQLAlchemy models.

Design rules (see docs/design.html §7):

* ``submissions``, ``artifacts``, ``grader_runs`` and ``assignment_versions``
  are insert-only. Application code never updates them; in production the
  API's database role has no UPDATE grant on those tables.
* Every row that can carry student data hangs off an ``enrollments`` row,
  which is scoped to one offering. Authorization always starts from the
  offering.
* PII is limited to NetID and an optional display name.

Types are chosen to run on PostgreSQL in production and SQLite in unit tests
(``Uuid``, ``JSON``, non-native enums).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    student = "student"
    ta = "ta"
    instructor = "instructor"


class EnrollmentStatus(str, enum.Enum):
    active = "active"
    dropped = "dropped"


class GradingMode(str, enum.Enum):
    auto = "auto"
    manual = "manual"
    hybrid = "hybrid"


class SubmissionStatus(str, enum.Enum):
    received = "received"
    grading = "grading"
    graded = "graded"
    failed = "failed"


class RunKind(str, enum.Enum):
    autograde = "autograde"
    render = "render"
    ai_suggest = "ai_suggest"


class RunStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, length=16, values_callable=lambda x: [m.value for m in x])


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    netid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="user")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    offerings: Mapped[list[Offering]] = relationship(back_populates="course")


class Offering(Base):
    __tablename__ = "offerings"
    __table_args__ = (UniqueConstraint("course_id", "term", name="uq_offering_course_term"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    term: Mapped[str] = mapped_column(String(32))  # e.g. "2026-fall"
    title: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # settings keys: join_code, allow_join, public_student_notebooks, retention_until
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    course: Mapped[Course] = relationship(back_populates="offerings")
    sections: Mapped[list[Section]] = relationship(back_populates="offering")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="offering")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="offering")


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("offering_id", "name", name="uq_section_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offerings.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))

    offering: Mapped[Offering] = relationship(back_populates="sections")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("offering_id", "user_id", name="uq_enrollment"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offerings.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sections.id"))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.student)
    status: Mapped[EnrollmentStatus] = mapped_column(
        _enum(EnrollmentStatus), default=EnrollmentStatus.active
    )
    # TA scoping: list of section ids the TA may grade; empty = all sections.
    ta_sections: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="enrollments")
    offering: Mapped[Offering] = relationship(back_populates="enrollments")
    section: Mapped[Section | None] = relationship()


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("offering_id", "slug", name="uq_assignment_slug"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offerings.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # settings keys: due_at, late_policy, attempts_allowed (int|null), grade_policy
    # (latest|highest|first|selected), environments [..], log_checks (bool),
    # canvas_assignment_id, required_datasets [..]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    offering: Mapped[Offering] = relationship(back_populates="assignments")
    versions: Mapped[list[AssignmentVersion]] = relationship(
        back_populates="assignment", order_by="AssignmentVersion.version"
    )
    questions: Mapped[list[Question]] = relationship(
        back_populates="assignment", order_by="Question.order"
    )


class AssignmentVersion(Base):
    """Immutable. One row per publish."""

    __tablename__ = "assignment_versions"
    __table_args__ = (UniqueConstraint("assignment_id", "version", name="uq_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    instructor_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    student_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    cell_hashes: Mapped[dict] = mapped_column(JSON, default=dict)
    question_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    published_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignment: Mapped[Assignment] = relationship(back_populates="versions")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("assignment_id", "qid", name="uq_question_qid"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    qid: Mapped[str] = mapped_column(String(64))  # stable, e.g. "glm-q03"
    title: Mapped[str] = mapped_column(String(200))
    order: Mapped[int] = mapped_column(Integer, default=0)
    max_points: Mapped[float] = mapped_column(Numeric(8, 2), default=1)
    auto_points_max: Mapped[float] = mapped_column(Numeric(8, 2), default=0)
    grading_mode: Mapped[GradingMode] = mapped_column(_enum(GradingMode), default=GradingMode.auto)
    check_keys: Mapped[list] = mapped_column(JSON, default=list)
    rubric_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rubrics.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    assignment: Mapped[Assignment] = relationship(back_populates="questions")
    rubric: Mapped[Rubric | None] = relationship()


class Rubric(Base):
    __tablename__ = "rubrics"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offerings.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    items: Mapped[list] = mapped_column(JSON, default=list)
    # items: [{"key": "r1", "label": "...", "points": 2, "description": "..."}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    """Content-addressed blob metadata. Bytes live in the artifact store."""

    __tablename__ = "artifacts"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))  # notebook|render|log|feedback|roster
    storage_key: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Submission(Base):
    """Immutable attempt."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "question_id", "attempt_no", name="uq_attempt"),
        UniqueConstraint(
            "enrollment_id", "question_id", "client_submission_id", name="uq_client_submission"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollments.id"), index=True)
    assignment_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment_versions.id"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notebook_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    outputs_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    render_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    client_check_results: Mapped[list] = mapped_column(JSON, default=list)
    client_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # Idempotency key chosen by the widget per click; a retry returns the same attempt.
    client_submission_id: Mapped[str | None] = mapped_column(String(64))
    # status is the one mutable column, advanced only by the worker.
    status: Mapped[SubmissionStatus] = mapped_column(
        _enum(SubmissionStatus), default=SubmissionStatus.received
    )

    enrollment: Mapped[Enrollment] = relationship()
    question: Mapped[Question] = relationship()
    version: Mapped[AssignmentVersion] = relationship()
    scores: Mapped[list[Score]] = relationship(back_populates="submission")
    runs: Mapped[list[GraderRun]] = relationship(back_populates="submission")


class GraderRun(Base):
    __tablename__ = "grader_runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    kind: Mapped[RunKind] = mapped_column(_enum(RunKind), default=RunKind.autograde)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), default=RunStatus.queued)
    grader_version: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    log_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))

    submission: Mapped[Submission] = relationship(back_populates="runs")


class Score(Base):
    """One row per grading action on a submission; the latest ``is_final`` wins."""

    __tablename__ = "scores"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id"), index=True)
    auto_points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    manual_points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    rubric_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback: Mapped[str | None] = mapped_column(Text)
    suggested_points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    suggested_feedback: Mapped[str | None] = mapped_column(Text)
    grader_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="scores")

    @property
    def total(self) -> float:
        return float(self.auto_points or 0) + float(self.manual_points or 0)


class QuestionGrade(Base):
    """The official grade for (enrollment, question), derived from the attempt policy."""

    __tablename__ = "question_grades"
    __table_args__ = (UniqueConstraint("enrollment_id", "question_id", name="uq_qgrade"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollments.id"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), index=True)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("submissions.id"))
    points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CheckEvent(Base):
    __tablename__ = "check_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    enrollment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollments.id"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id"), index=True)
    check_key: Mapped[str] = mapped_column(String(120))
    passed: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class GradeAudit(Base):
    __tablename__ = "grade_audit"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    offering_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offerings.id"), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WebSession(Base):
    __tablename__ = "web_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    saml_name_id: Mapped[str | None] = mapped_column(String(300))
    saml_session_index: Mapped[str | None] = mapped_column(String(300))


class DeviceCode(Base):
    __tablename__ = "device_codes"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    device_code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    client: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RosterUpload(Base):
    """Stored Canvas gradebook exports, used both for roster import and Canvas export."""

    __tablename__ = "roster_uploads"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    offering_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offerings.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
