"""Three tables. Amounts and dates are TEXT; ``modified`` and rule results are derived."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_width: Mapped[float] = mapped_column(Float, nullable=False)
    page_height: Mapped[float] = mapped_column(Float, nullable=False)
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(16), nullable=False)
    extraction_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Optimistic concurrency: every real business change bumps this exactly once, explicitly.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_at: Mapped[str | None] = mapped_column(String(32))
    confirmed_by: Mapped[str | None] = mapped_column(String(64))

    fields: Mapped[list[DocumentField]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    events: Mapped[list[AuditEvent]] = relationship(
        back_populates="document", order_by="AuditEvent.id"
    )

    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class DocumentField(Base):
    __tablename__ = "document_fields"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_value: Mapped[str | None] = mapped_column(Text)
    source_parse_status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_json: Mapped[str | None] = mapped_column(Text)
    initial_extracted_value: Mapped[str | None] = mapped_column(Text)
    current_value: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[str | None] = mapped_column(String(32))
    verified_by: Mapped[str | None] = mapped_column(String(64))

    document: Mapped[Document] = relationship(back_populates="fields")


class AuditEvent(Base):
    """Append-only operation history. No update or delete path exists in the application."""

    __tablename__ = "audit_events"
    __table_args__ = {"sqlite_autoincrement": True}  # ids are never reused

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[Document] = relationship(back_populates="events")
