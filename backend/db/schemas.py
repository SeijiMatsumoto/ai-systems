import enum
import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class DocumentType(str, enum.Enum):
    """Document type enumeration"""

    GENERIC = "generic"
    FILING = "filing"
    EARNINGS = "earnings"
    ARTICLE = "article"


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
    embedding = Column(ARRAY(Float, dimensions=1), nullable=True)

    # Denormalized attributes strictly used for fast vector search filtering
    filter_metadata = Column(JSON, default={})

    # Relationship
    document = relationship("Document", back_populates="chunks")
