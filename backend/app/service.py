from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, or_, func
from .models import Patient, Appointment, Encounter, Task, AuditEvent, NoteVersion, now, new_id

CLINIC_TZ = ZoneInfo("America/Los_Angeles")


def iso(value):
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def patient_json(p):
    today = now().astimezone(CLINIC_TZ).date()
    dob = p.date_of_birth
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return {"id": p.id, "mrn": p.mrn, "firstName": p.first_name, "lastName": p.last_name,
            "name": f"{p.first_name} {p.last_name}", "dateOfBirth": iso(dob), "age": age,
            "sex": p.sex, "phone": p.phone, "email": p.email, "status": p.status,
            "allergies": p.allergies, "allergyStatus": "recorded" if p.allergies else "unknown",
            "conditions": p.conditions, "medications": p.medications,
            "lastVisit": iso(p.last_visit), "avatarColor": p.avatar_color}


def appointment_json(a, patient):
    return {"id": a.id, "patientId": a.patient_id, "patientName": f"{patient.first_name} {patient.last_name}",
            "patientMrn": patient.mrn, "avatarColor": patient.avatar_color,
            "startTime": iso(a.start_time), "durationMinutes": a.duration_minutes, "type": a.type,
            "status": a.status, "clinician": a.clinician, "room": a.room}


def encounter_json(e, patient):
    return {"id": e.id, "patientId": e.patient_id, "patientName": f"{patient.first_name} {patient.last_name}",
            "startedAt": iso(e.started_at), "type": e.type, "status": e.status,
            "clinician": e.clinician, "chiefComplaint": e.chief_complaint,
            "note": e.note, "vitals": e.vitals, "updatedAt": iso(e.updated_at), "version": e.version,
            "signedAt": iso(e.signed_at), "signedBy": e.signed_by, "signatureHash": e.signature_hash}


def note_hash(note):
    return hashlib.sha256(json.dumps(note, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EHRService:
    def __init__(self, database, principal):
        self.db, self.principal = database, principal

    def require(self, scope):
        if scope not in self.principal.scopes:
            with self.db.session() as s:
                self.audit(s, "access.denied", "authorization", outcome="denied")
            raise HTTPException(403, f"Required scope: {scope}")

    def audit(self, session, action, resource_type, resource_id="collection", outcome="success"):
        session.add(AuditEvent(tenant_id=self.principal.tenant_id, actor_id=self.principal.actor_id,
                               action=action, resource_type=resource_type, resource_id=resource_id, outcome=outcome))

    def deny_note_write(self, ident, action, status, message):
        # Persist rejected clinical write attempts independently of the rolled-back edit.
        with self.db.session() as audit_session:
            self.audit(audit_session, action, "encounter", ident, "denied")
        raise HTTPException(status, message)

    def query(self, model):
        return select(model).where(model.tenant_id == self.principal.tenant_id)

    def get(self, session, model, ident, *, lock=False):
        query = self.query(model).where(model.id == ident)
        if lock:
            query = query.with_for_update()
        value = session.scalar(query)
        if value is None:
            # A failed lookup is audited separately because the enclosing transaction rolls back.
            with self.db.session() as audit_session:
                self.audit(audit_session, "read.missing", model.__tablename__, ident, "not_found")
            raise HTTPException(404, "Record not found")
        return value

    def patients(self, search="", limit=100):
        self.require("ehr:read")
        with self.db.session() as s:
            q = self.query(Patient)
            if search:
                # Escape SQL LIKE wildcards; search values are bound parameters.
                term = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                q = q.where(or_((Patient.first_name + " " + Patient.last_name).ilike(term, escape="\\"), Patient.mrn.ilike(term, escape="\\")))
            records = s.scalars(q.order_by(Patient.last_name).limit(limit)).all()
            self.audit(s, "patients.search", "patients")
            return [patient_json(p) for p in records]

    def patient_chart(self, ident):
        self.require("ehr:read")
        with self.db.session() as s:
            p = self.get(s, Patient, ident)
            appointments = s.scalars(self.query(Appointment).where(Appointment.patient_id == ident).order_by(Appointment.start_time.desc()).limit(100)).all()
            encounters = s.scalars(self.query(Encounter).where(Encounter.patient_id == ident).order_by(Encounter.started_at.desc()).limit(100)).all()
            self.audit(s, "patient.chart.read", "patient", ident)
            return {"patient": patient_json(p), "appointments": [appointment_json(a, p) for a in appointments], "encounters": [encounter_json(e, p) for e in encounters]}

    def create_patient(self, data):
        self.require("ehr:write")
        with self.db.session() as s:
            p = Patient(tenant_id=self.principal.tenant_id, mrn="TOF-" + new_id().replace("-", "")[:10].upper(),
                        first_name=data.firstName, last_name=data.lastName, date_of_birth=data.dateOfBirth,
                        sex=data.sex.lower(), phone=data.phone, email=data.email)
            s.add(p)
            s.flush()
            self.audit(s, "patient.create", "patient", p.id)
            return patient_json(p)

    def appointments(self, day=None, patient_id=None):
        self.require("ehr:read")
        with self.db.session() as s:
            q = self.query(Appointment)
            if day:
                start = datetime.combine(day, datetime.min.time(), tzinfo=CLINIC_TZ)
                q = q.where(Appointment.start_time >= start.astimezone(timezone.utc), Appointment.start_time < (start + timedelta(days=1)).astimezone(timezone.utc))
            if patient_id:
                self.get(s, Patient, patient_id)
                q = q.where(Appointment.patient_id == patient_id)
            appointments = s.scalars(q.order_by(Appointment.start_time).limit(200)).all()
            self.audit(s, "appointments.list", "appointments")
            return [appointment_json(a, self.get(s, Patient, a.patient_id)) for a in appointments]

    def create_appointment(self, data):
        self.require("ehr:write")
        with self.db.session() as s:
            patient = self.get(s, Patient, data.patientId)
            a = Appointment(tenant_id=self.principal.tenant_id, patient_id=patient.id,
                            start_time=data.startTime.astimezone(timezone.utc), duration_minutes=data.durationMinutes,
                            type=data.type, clinician=data.clinician or self.principal.actor_id, room=data.room)
            s.add(a)
            s.flush()
            self.audit(s, "appointment.create", "appointment", a.id)
            return appointment_json(a, patient)

    def update_appointment(self, ident, status):
        self.require("ehr:write")
        with self.db.session() as s:
            a = self.get(s, Appointment, ident, lock=True)
            a.status = status
            self.audit(s, "appointment.status.update", "appointment", a.id)
            return appointment_json(a, self.get(s, Patient, a.patient_id))

    def encounters(self, patient_id=None):
        self.require("ehr:read")
        with self.db.session() as s:
            q = self.query(Encounter)
            if patient_id:
                self.get(s, Patient, patient_id)
                q = q.where(Encounter.patient_id == patient_id)
            records = s.scalars(q.order_by(Encounter.started_at.desc()).limit(100)).all()
            self.audit(s, "encounters.list", "encounters")
            return [encounter_json(e, self.get(s, Patient, e.patient_id)) for e in records]

    def encounter(self, ident):
        self.require("ehr:read")
        with self.db.session() as s:
            e = self.get(s, Encounter, ident)
            self.audit(s, "encounter.read", "encounter", ident)
            return encounter_json(e, self.get(s, Patient, e.patient_id))

    def create_encounter(self, data):
        self.require("ehr:write")
        with self.db.session() as s:
            p = self.get(s, Patient, data.patientId)
            e = Encounter(tenant_id=self.principal.tenant_id, patient_id=p.id, type=data.type, chief_complaint=data.chiefComplaint, clinician=self.principal.actor_id)
            s.add(e)
            s.flush()
            self.snapshot(s, e)
            self.audit(s, "encounter.create", "encounter", e.id)
            return encounter_json(e, p)

    def snapshot(self, session, encounter):
        session.add(NoteVersion(tenant_id=self.principal.tenant_id, encounter_id=encounter.id,
                                version=encounter.version, note=dict(encounter.note), actor_id=self.principal.actor_id,
                                content_hash=note_hash(encounter.note), status=encounter.status))

    def update_note(self, ident, data):
        self.require("ehr:write")
        with self.db.session() as s:
            e = self.get(s, Encounter, ident, lock=True)
            if e.status == "signed":
                self.deny_note_write(ident, "encounter.immutable.denied", 409, "Signed notes are immutable; amendments are not available in this starter")
            if data.expectedVersion != e.version:
                self.deny_note_write(ident, "encounter.stale.denied", 409, "Note changed since it was loaded; reload before saving")
            if "assessmentPlan" in e.note and data.model_fields_set & {"assessment", "plan"}:
                self.deny_note_write(ident, "encounter.legacy-fields.denied", 422, "This note uses assessmentPlan; edit assessmentPlan instead of legacy assessment or plan fields")
            changes = data.model_dump(exclude_none=True, exclude={"status", "expectedVersion"})
            updated_note = {**e.note, **changes}
            if "assessmentPlan" in changes:
                # Conversion is explicit on save; existing/signed versions are never rewritten.
                updated_note.pop("assessment", None)
                updated_note.pop("plan", None)
            required_sections = ("subjective", "objective", "assessmentPlan") if "assessmentPlan" in updated_note else ("subjective", "objective", "assessment", "plan")
            if data.status == "signed" and any(not updated_note.get(k, "").strip() for k in required_sections):
                message = "Complete Subjective, Objective, and Assessment & Plan before signing" if "assessmentPlan" in updated_note else "Complete all four SOAP sections before signing"
                self.deny_note_write(ident, "encounter.incomplete-sign.denied", 422, message)
            e.note = updated_note
            e.version += 1
            e.updated_at = now()
            if data.status == "signed":
                e.status, e.signed_by, e.signed_at = "signed", self.principal.actor_id, now()
                e.signature_hash = note_hash(e.note)
            self.snapshot(s, e)
            self.audit(s, "encounter.sign" if e.status == "signed" else "encounter.note.update", "encounter", ident)
            return encounter_json(e, self.get(s, Patient, e.patient_id))

    def note_history(self, ident):
        self.require("ehr:read")
        with self.db.session() as s:
            self.get(s, Encounter, ident)
            versions = s.scalars(self.query(NoteVersion).where(NoteVersion.encounter_id == ident).order_by(NoteVersion.version)).all()
            self.audit(s, "encounter.history.read", "encounter", ident)
            return [{"version": n.version, "note": n.note, "actorId": n.actor_id, "timestamp": iso(n.timestamp), "contentHash": n.content_hash, "status": n.status} for n in versions]

    def clinical_review_snapshot(self, ident, expected_version, operation):
        """Read the authorized saved note once; never hold a row lock during inference."""
        self.require("ehr:read")
        with self.db.session() as s:
            encounter = self.get(s, Encounter, ident)
            if encounter.version != expected_version:
                with self.db.session() as audit_session:
                    self.audit(audit_session, f"clinical_ai.{operation}.stale", "encounter", ident, "denied")
                raise HTTPException(409, "Note changed since it was loaded; reload before requesting review")
            section_keys = [("subjective", "Subjective"), ("objective", "Objective")]
            section_keys += [("assessmentPlan", "Assessment & Plan")] if "assessmentPlan" in encounter.note else [("assessment", "Assessment"), ("plan", "Plan")]
            sections = [(heading, encounter.note.get(key, "")) for key, heading in section_keys]
            if not any(value.strip() for _, value in sections):
                with self.db.session() as audit_session:
                    self.audit(audit_session, f"clinical_ai.{operation}.empty", "encounter", ident, "denied")
                raise HTTPException(422, "Save note content before requesting clinical AI review")
            snapshot = {"encounterId": encounter.id, "encounterVersion": encounter.version,
                        "text": "\n\n".join(f"{heading}:\n{value}" for heading, value in sections)}
            self.audit(s, f"clinical_ai.{operation}.requested", "encounter", ident)
            return snapshot

    def clinical_review_audit(self, ident, operation, *, model=None, failure=None):
        with self.db.session() as s:
            if failure:
                self.audit(s, f"clinical_ai.{operation}.failed.{failure}", "encounter", ident, "failure")
            else:
                self.audit(s, f"clinical_ai.{operation}.completed", "encounter", ident, "review_required")
                # Current audit schema has no arbitrary metadata field. A stable model
                # identity/revision fingerprint preserves provenance without a migration.
                fingerprint = hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                self.audit(s, f"clinical_ai.{operation}.model", "ai_model", fingerprint, "review_required")

    def clinical_ai_verification_audit(self, stage):
        with self.db.session() as s:
            self.audit(s, f"clinical_ai.verify.{stage}", "ai_provider", "utility-medium", "failure" if stage == "failed" else "success")

    def verify_clinical_review_version(self, ident, expected_version, operation):
        with self.db.session() as s:
            encounter = self.get(s, Encounter, ident)
            if encounter.version != expected_version:
                with self.db.session() as audit_session:
                    self.audit(audit_session, f"clinical_ai.{operation}.stale-after-review", "encounter", ident, "denied")
                raise HTTPException(409, "The saved note changed during clinical AI review; reload and request a new review")

    def tasks(self):
        self.require("ehr:read")
        with self.db.session() as s:
            records = s.scalars(self.query(Task).order_by(Task.due_date).limit(100)).all()
            result = []
            for task in records:
                p = self.get(s, Patient, task.patient_id)
                result.append({"id": task.id, "patientId": p.id, "patientName": f"{p.first_name} {p.last_name}", "title": task.title, "priority": task.priority, "status": task.status, "dueDate": iso(task.due_date)})
            self.audit(s, "tasks.list", "tasks")
            return result

    def update_task(self, ident, status):
        self.require("ehr:write")
        with self.db.session() as s:
            task = self.get(s, Task, ident, lock=True)
            task.status = status
            p = self.get(s, Patient, task.patient_id)
            self.audit(s, "task.status.update", "task", ident)
            return {"id": task.id, "patientId": p.id, "patientName": f"{p.first_name} {p.last_name}", "title": task.title, "priority": task.priority, "status": task.status, "dueDate": iso(task.due_date)}

    def audit_events(self):
        self.require("ehr:audit")
        with self.db.session() as s:
            events = s.scalars(self.query(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(100)).all()
            self.audit(s, "audit.list", "audit")
            return [{"id": e.id, "timestamp": iso(e.timestamp), "actorId": e.actor_id, "action": e.action, "resourceType": e.resource_type, "resourceId": e.resource_id, "outcome": e.outcome} for e in events]

    def dashboard(self):
        self.require("ehr:read")
        today = now().astimezone(CLINIC_TZ).date()
        appointments, tasks = self.appointments(today), self.tasks()
        with self.db.session() as s:
            open_encounters = s.scalar(select(func.count()).select_from(Encounter).where(Encounter.tenant_id == self.principal.tenant_id, Encounter.status == "draft"))
            total_patients = s.scalar(select(func.count()).select_from(Patient).where(Patient.tenant_id == self.principal.tenant_id))
            pending_tasks = s.scalar(select(func.count()).select_from(Task).where(Task.tenant_id == self.principal.tenant_id, Task.status == "open"))
            start = datetime.combine(today, datetime.min.time(), tzinfo=CLINIC_TZ)
            appointment_count = select(func.count()).select_from(Appointment).where(Appointment.tenant_id == self.principal.tenant_id, Appointment.start_time >= start.astimezone(timezone.utc), Appointment.start_time < (start + timedelta(days=1)).astimezone(timezone.utc))
            appointments_today = s.scalar(appointment_count)
            checked_in = s.scalar(appointment_count.where(Appointment.status == "checked-in"))
            patients = [patient_json(p) for p in s.scalars(self.query(Patient).order_by(Patient.created_at.desc()).limit(6)).all()]
            self.audit(s, "dashboard.read", "dashboard")
        return {"today": iso(today), "stats": {"appointmentsToday": appointments_today, "checkedIn": checked_in, "openEncounters": open_encounters, "pendingTasks": pending_tasks, "totalPatients": total_patients}, "appointments": appointments, "recentPatients": patients, "tasks": tasks}
