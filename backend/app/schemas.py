from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PatientCreate(InputModel):
    firstName: str = Field(min_length=1, max_length=100)
    lastName: str = Field(min_length=1, max_length=100)
    dateOfBirth: date
    sex: Literal["female", "male", "other", "unknown", "Female", "Male", "Other", "Unknown"]
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)

    @field_validator("dateOfBirth")
    @classmethod
    def birth_date(cls, value):
        if value > date.today() or value.year < 1900:
            raise ValueError("Date of birth must be between 1900 and today")
        return value

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        if value and ("@" not in value or "." not in value.rsplit("@", 1)[-1]):
            raise ValueError("Invalid email address")
        return value


class AppointmentCreate(InputModel):
    patientId: str = Field(min_length=1, max_length=36)
    startTime: datetime
    durationMinutes: int = Field(default=30, ge=5, le=240)
    type: str = Field(default="Follow-up", min_length=1, max_length=80)
    clinician: str | None = Field(default=None, min_length=1, max_length=120)
    room: str = Field(default="Room 1", min_length=1, max_length=30)

    @field_validator("startTime")
    @classmethod
    def timezone_required(cls, value):
        if value.utcoffset() is None:
            raise ValueError("startTime must include a timezone offset")
        return value


class AppointmentStatus(InputModel):
    status: Literal["scheduled", "checked-in", "in-progress", "completed", "cancelled", "no-show"]


class EncounterCreate(InputModel):
    patientId: str = Field(min_length=1, max_length=36)
    type: str = Field(default="Office visit", min_length=1, max_length=80)
    chiefComplaint: str = Field(default="", max_length=500)


class NoteUpdate(InputModel):
    expectedVersion: int = Field(ge=1)
    subjective: str | None = Field(default=None, max_length=20000)
    objective: str | None = Field(default=None, max_length=20000)
    assessment: str | None = Field(default=None, max_length=20000)
    plan: str | None = Field(default=None, max_length=20000)
    assessmentPlan: str | None = Field(default=None, max_length=40960)
    status: Literal["draft", "signed"] | None = None

    @model_validator(mode="after")
    def unambiguous_assessment_plan(self):
        supplied = self.model_fields_set
        if "assessmentPlan" in supplied:
            if supplied & {"assessment", "plan"}:
                raise ValueError("Send assessmentPlan or legacy assessment/plan fields, never both")
            if self.assessmentPlan is None:
                raise ValueError("assessmentPlan must be a string when provided")
        return self


class TaskStatus(InputModel):
    status: Literal["open", "completed"]


class ClinicalReviewRequest(InputModel):
    expectedVersion: int = Field(ge=1)
    operation: Literal["deidentify", "entities"]


class ClinicalAIVerifyRequest(InputModel):
    """Only an empty object is accepted; the synthetic input is fixed server-side."""
    pass
