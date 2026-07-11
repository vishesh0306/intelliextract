import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.job import Job


class JobResult(Base):
    __tablename__ = "job_results"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), primary_key=True
    )
    extracted_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="result")
