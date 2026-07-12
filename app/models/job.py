import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.job_attempt import JobAttempt
    from app.models.job_result import JobResult


class JobStatus(enum.StrEnum):
    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    EXTRACTING_AI = "EXTRACTING_AI"
    VALIDATING = "VALIDATING"
    DONE = "DONE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=20),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    # Set on jobs created via the Phase 8 cache short-circuit — lets
    # /metrics compute a real cache-hit ratio and average processing time
    # for genuinely-processed jobs, instead of guessing from timestamps.
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    api_key: Mapped["ApiKey"] = relationship(back_populates="jobs")
    result: Mapped["JobResult | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    attempts: Mapped[list["JobAttempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
