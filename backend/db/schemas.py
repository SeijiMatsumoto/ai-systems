import enum
import uuid

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class DocumentType(str, enum.Enum):
    """Document type enumeration"""

    GENERIC = "generic"
    FILING = "filing"
    EARNINGS = "earnings"
    ARTICLE = "article"


class ResearchRunStatus(str, enum.Enum):
    """Lifecycle state for a research-agent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """Document-level table (Canonical metadata & source of truth)"""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Use a named SQLEnum for Postgres; name is required for CREATE TYPE
    document_type = Column(
        SQLEnum(DocumentType, name="document_type"),
        nullable=False,
        default=DocumentType.GENERIC,
    )
    reference_id = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=False)
    source_url = Column(String)
    author = Column(String)
    created_at = Column(DateTime(timezone=True), default=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )

    # Relationship
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    filter_metadata = Column(JSON, default={})


class DocumentChunk(Base):
    """Chunk & Embedding table (Chunk text + vector + filter keys)"""

    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(VECTOR(1536), nullable=True)

    # Denormalized attributes strictly used for fast vector search filtering
    filter_metadata = Column(JSON, default={})

    # Relationship
    document = relationship("Document", back_populates="chunks")


class ResearchRun(Base):
    """One attempt to produce and verify a research briefing."""

    __tablename__ = "research_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_fingerprint = Column(String(64), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), nullable=False)
    status = Column(
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
    request_payload = Column(JSONB, nullable=False)
    briefing_payload = Column(JSONB, nullable=True)
    verification_payload = Column(JSONB, nullable=True)
    usage_payload = Column(JSONB, nullable=False, default=dict)
    error_payload = Column(JSONB, nullable=True)

    model_name = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    tool_version = Column(String, nullable=False)
    schema_version = Column(String, nullable=False, default="1")

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
