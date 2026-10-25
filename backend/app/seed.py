"""Synthetic-only, tenant-scoped and idempotent demo fixtures."""
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from .models import Patient, Appointment, Encounter, Task, AuditEvent, NoteVersion, now
from .service import CLINIC_TZ, note_hash


def seed_demo(database):
    today = now().astimezone(CLINIC_TZ).date()
    names = [
        ("Eleanor", "Pena", "1988-04-18", "female", "sage"),
        ("Robert", "Fox", "1972-09-06", "male", "blue"),
        ("Dianne", "Russell", "1995-12-21", "female", "peach"),
        ("Albert", "Flores", "1964-06-03", "male", "lavender"),
        ("Courtney", "Henry", "1983-02-14", "female", "sage"),
        ("Jerome", "Bell", "1990-11-09", "male", "blue"),
        ("Bessie", "Cooper", "1958-07-25", "female", "peach"),
        ("Cameron", "Williamson", "2001-03-12", "male", "lavender"),
    ]
    with database.session() as session:
        if session.scalar(select(Patient.id).where(Patient.tenant_id == "demo-clinic").limit(1)):
            return
        for index, (first, last, birth, sex, color) in enumerate(names):
            patient = Patient(id=f"demo-patient-{index+1}", tenant_id="demo-clinic", mrn=f"TOF-{10001+index}",
                              first_name=first, last_name=last, date_of_birth=date.fromisoformat(birth), sex=sex,
                              phone=f"(555) 010-{1000+index}", email=f"{first.lower()}.{last.lower()}@example.invalid",
                              allergies=["Penicillin"] if index == 0 else [],
                              conditions=["Hypertension"] if index in (1, 3, 6) else ["Annual wellness"] if index == 2 else [],
                              medications=["Demo medication list — verification required"] if index in (1, 3) else [],
                              last_visit=today-timedelta(days=21+index*3), avatar_color=color)
            session.add(patient)
            session.flush()
            if index < 6:
                local_time = datetime.combine(today, datetime.min.time(), tzinfo=CLINIC_TZ).replace(hour=9+index//2, minute=30*(index%2))
                session.add(Appointment(id=f"demo-appointment-{index+1}", tenant_id="demo-clinic", patient_id=patient.id,
                                        start_time=local_time.astimezone(timezone.utc), duration_minutes=30,
                                        type=["Follow-up", "Annual wellness", "New patient", "Follow-up", "Consultation", "Follow-up"][index],
                                        status=["checked-in", "in-progress", "scheduled", "scheduled", "scheduled", "scheduled"][index],
                                        room=f"Room {1+index%3}", clinician="Dr. Sarah Mitchell (synthetic)"))
            if index < 3:
                note = {"subjective": "Synthetic demonstration: patient presents for a routine follow-up.",
                        "objective": "Synthetic demonstration observations. Verify all findings before clinical use.",
                        "assessment": "", "plan": ""}
                encounter = Encounter(id=f"demo-encounter-{index+1}", tenant_id="demo-clinic", patient_id=patient.id,
                                      chief_complaint=["Routine follow-up", "Annual wellness visit", "Establish care"][index], note=note, clinician="Dr. Sarah Mitchell (synthetic)",
                                      vitals={"bloodPressure": "118/76", "heartRate": 72, "temperature": 98.2, "oxygenSaturation": 99, "weight": 148})
                session.add(encounter)
                session.flush()
                session.add(NoteVersion(tenant_id="demo-clinic", encounter_id=encounter.id, version=1, note=note,
                                        actor_id="demo-seed", content_hash=note_hash(note), status="draft"))
            if index < 4:
                session.add(Task(id=f"demo-task-{index+1}", tenant_id="demo-clinic", patient_id=patient.id,
                                 title=["Complete visit documentation", "Review patient history", "Confirm intake information", "Schedule follow-up visit"][index],
                                 priority="high" if index == 0 else "normal", due_date=today))
        session.add(AuditEvent(tenant_id="demo-clinic", actor_id="demo-seed", action="demo.seed", resource_type="system"))
