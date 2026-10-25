from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid4())


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("tenant_id", "mrn", name="uq_patient_tenant_mrn"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    mrn: Mapped[str] = mapped_column(String(32))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[datetime] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(30))
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    medications: Mapped[list] = mapped_column(JSON, default=list)
    last_visit: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    avatar_color: Mapped[str] = mapped_column(String(20), default="sage")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    type: Mapped[str] = mapped_column(String(80), default="Follow-up")
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    clinician: Mapped[str] = mapped_column(String(120))
    room: Mapped[str] = mapped_column(String(30), default="Room 1")


class Encounter(Base):
    __tablename__ = "encounters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    type: Mapped[str] = mapped_column(String(80), default="Office visit")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    clinician: Mapped[str] = mapped_column(String(120))
    chief_complaint: Mapped[str] = mapped_column(String(500), default="")
    note: Mapped[dict] = mapped_column(JSON, default=lambda: {"subjective": "", "objective": "", "assessment": "", "plan": ""})
    vitals: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signature_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class NoteVersion(Base):
    __tablename__ = "note_versions"
    __table_args__ = (UniqueConstraint("encounter_id", "version", name="uq_encounter_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    note: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_date: Mapped[datetime] = mapped_column(Date)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(100), default="collection")
    outcome: Mapped[str] = mapped_column(String(20), default="success")


class SchemaVersion(Base):
    __tablename__ = "schema_versions"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
