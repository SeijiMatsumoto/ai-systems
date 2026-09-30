import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentType(str, enum.Enum):
    """Document type enumeration"""

    GENERIC = "generic"
    FILING = "filing"
    ARTICLE = "article"


class ResearchRunStatus(str, enum.Enum):
    """Lifecycle state for a research-agent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LlmRun(Base):
    """Shared identity and lifecycle for one top-level AI-system execution."""

    __tablename__ = "llm_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_llm_runs_status",
        ),
        Index("ix_llm_runs_system_created_at", "system_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    system_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    logfire_trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentSimulationOutput(Base):
    """Saved response and workflow trace for one incident simulation."""

    __tablename__ = "incident_simulation_outputs"
    __table_args__ = (Index("ix_incident_simulation_outputs_created_at", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    response_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Document(Base):
    """Document-level table (Canonical metadata & source of truth)"""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Use a named SQLEnum for Postgres; name is required for CREATE TYPE
    document_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(DocumentType, name="document_type"),
        nullable=False,
        default=DocumentType.GENERIC,
    )
    reference_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )

    # Relationship
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    filter_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=dict, nullable=True
    )


class DocumentChunk(Base):
    """Chunk & Embedding table (Chunk text + vector + filter keys)"""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(1536), nullable=True)

    # Denormalized attributes strictly used for fast vector search filtering
    filter_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=dict, nullable=True
    )

    # Relationship
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")


class ResearchRun(Base):
    """One attempt to produce and verify a research briefing."""

    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ResearchRunStatus] = mapped_column(
        SQLEnum(
            ResearchRunStatus,
            name="research_run_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        nullable=False,
        default=ResearchRunStatus.PENDING,
        index=True,
    )

    # These payloads are validated by Pydantic at the application boundary.
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    briefing_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    verification_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    usage_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    error_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    checkpoint_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    checkpoint_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    model_name: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    tool_version: Mapped[str] = mapped_column(String, nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False, default="1")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
