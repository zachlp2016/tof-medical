import { useState } from "react";
import type { FormEvent } from "react";
import { Check, LockKeyhole, Save } from "lucide-react";
import { api, displayDate, localDate, useApi } from "./api";
import type { Encounter, Patient } from "./types";
import { ErrorMessage, Field, Loading, Modal, Status } from "./ui";
import { ClinicalTextReview } from "./clinical-review";
import { normalizeNote } from "./note";
import type { EditorNote } from "./note";

export function PatientForm({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (patient: Patient) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    setSaving(true);
    setError("");
    try {
      onCreated(
        await api<Patient>("/patients", {
          method: "POST",
          body: JSON.stringify(data),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal title="Add a patient" onClose={onClose}>
      <form onSubmit={submit}>
        <p className="form-intro">
          Create a patient record for your clinical workspace.
        </p>
        <div className="form-grid">
          <Field label="First name">
            <input
              name="firstName"
              autoComplete="given-name"
              required
              autoFocus
              maxLength={100}
            />
          </Field>
          <Field label="Last name">
            <input
              name="lastName"
              autoComplete="family-name"
              required
              maxLength={100}
            />
          </Field>
          <Field label="Date of birth">
            <input name="dateOfBirth" type="date" required max={localDate()} />
          </Field>
          <Field label="Sex">
            <select name="sex" defaultValue="unknown">
              <option value="unknown">Unknown</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
            </select>
          </Field>
          <Field label="Email (optional)">
            <input name="email" type="email" autoComplete="email" />
          </Field>
          <Field label="Phone (optional)">
            <input name="phone" type="tel" autoComplete="tel" />
          </Field>
        </div>
        {error ? <ErrorMessage message={error} /> : null}
        <div className="modal-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" disabled={saving}>
            {saving ? "Adding…" : "Add patient"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function EncounterForm({
  patientId,
  onClose,
  onCreated,
}: {
  patientId?: string;
  onClose: () => void;
  onCreated: (encounter: Encounter) => void;
}) {
  const {
    data: patients,
    error: loadError,
    loading,
  } = useApi<Patient[]>("/patients");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      onCreated(
        await api<Encounter>("/encounters", {
          method: "POST",
          body: JSON.stringify(
            Object.fromEntries(new FormData(event.currentTarget)),
          ),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal title="New encounter" onClose={onClose}>
      <form onSubmit={submit}>
        <p className="form-intro">Start a clinical note for a patient.</p>
        {loading ? (
          <Loading />
        ) : loadError ? (
          <ErrorMessage message={loadError} />
        ) : (
          <div className="form-grid">
            <Field label="Patient" full>
              <select
                name="patientId"
                defaultValue={patientId || ""}
                required
                autoFocus
              >
                <option value="" disabled>
                  Select a patient
                </option>
                {patients?.map((patient) => (
                  <option key={patient.id} value={patient.id}>
                    {patient.name} · {patient.mrn}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Visit type" full>
              <select name="type" defaultValue="Office visit">
                <option>Office visit</option>
                <option>Follow-up</option>
                <option>Annual wellness</option>
                <option>Consultation</option>
                <option>Telehealth</option>
              </select>
            </Field>
            <Field label="Chief complaint" full>
              <textarea
                name="chiefComplaint"
                rows={3}
                required
                placeholder="Reason for today's visit"
                maxLength={500}
              />
            </Field>
          </div>
        )}
        {error ? <ErrorMessage message={error} /> : null}
        <div className="modal-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={saving || loading || !patients?.length}
          >
            {saving ? "Creating…" : "Start encounter"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function AppointmentForm({
  date,
  onClose,
  onCreated,
}: {
  date: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const {
    data: patients,
    error: loadError,
    loading,
  } = useApi<Patient[]>("/patients");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (!data.room) delete data.room;
    try {
      await api("/appointments", {
        method: "POST",
        body: JSON.stringify({
          ...data,
          startTime: new Date(String(data.startTime)).toISOString(),
          durationMinutes: Number(data.durationMinutes),
        }),
      });
      onCreated();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <Modal title="New appointment" onClose={onClose}>
      <form onSubmit={submit}>
        {loading ? (
          <Loading />
        ) : loadError ? (
          <ErrorMessage message={loadError} />
        ) : (
          <div className="form-grid">
            <Field label="Patient" full>
              <select name="patientId" required defaultValue="" autoFocus>
                <option value="" disabled>
                  Select a patient
                </option>
                {patients?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.mrn}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Date and time">
              <input
                name="startTime"
                type="datetime-local"
                defaultValue={`${date}T09:00`}
                required
              />
            </Field>
            <Field label="Duration">
              <select name="durationMinutes" defaultValue="30">
                <option value="15">15 minutes</option>
                <option value="30">30 minutes</option>
                <option value="45">45 minutes</option>
                <option value="60">60 minutes</option>
              </select>
            </Field>
            <Field label="Visit type">
              <select name="type">
                <option>Office visit</option>
                <option>Follow-up</option>
                <option>Annual wellness</option>
                <option>Consultation</option>
                <option>Telehealth</option>
              </select>
            </Field>
            <Field label="Clinician">
              <input name="clinician" required placeholder="Clinician name" />
            </Field>
            <Field label="Room (optional)">
              <input name="room" placeholder="e.g. Room 2" />
            </Field>
          </div>
        )}
        {error ? <ErrorMessage message={error} /> : null}
        <div className="modal-actions">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={saving || loading || !patients?.length}
          >
            {saving ? "Scheduling…" : "Schedule appointment"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function EncounterEditor({
  id,
  onClose,
  onSaved,
}: {
  id: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { data, error, loading, reload } = useApi<Encounter>(
    `/encounters/${id}`,
  );
  const [saved, setSaved] = useState(false);
  return (
    <Modal title="Encounter note" wide onClose={onClose}>
      {saved ? (
        <p className="success-message" role="status">
          <Check size={16} />
          Changes saved.
        </p>
      ) : null}
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : data ? (
        <NoteEditor
          key={`${data.id}-${data.version}`}
          encounter={data}
          onEditing={() => setSaved(false)}
          onSaved={() => {
            setSaved(true);
            reload();
            onSaved();
          }}
        />
      ) : null}
    </Modal>
  );
}
function NoteEditor({
  encounter,
  onSaved,
  onEditing,
}: {
  encounter: Encounter;
  onSaved: () => void;
  onEditing: () => void;
}) {
  const savedNote = normalizeNote(encounter.note);
  const [note, setNote] = useState<EditorNote>(() => savedNote);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirmSign, setConfirmSign] = useState(false);
  const [attested, setAttested] = useState(false);
  const signed = encounter.status === "signed";
  const dirty = (Object.keys(note) as (keyof EditorNote)[]).some(
    (key) => note[key] !== savedNote[key],
  );
  const complete = Object.values(note).every((text) => text.trim());
  async function save(sign = false) {
    setSaving(true);
    setError("");
    onEditing();
    try {
      await api(`/encounters/${encounter.id}/note`, {
        method: "PATCH",
        body: JSON.stringify({
          ...note,
          expectedVersion: encounter.version,
          status: sign ? "signed" : "draft",
        }),
      });
      setConfirmSign(false);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div>
      <div className="encounter-summary">
        <div>
          <h3>{encounter.patientName}</h3>
          <p>
            {encounter.type} · {displayDate(encounter.startedAt)} ·{" "}
            {encounter.clinician}
          </p>
        </div>
        <Status value={encounter.status} />
      </div>
      <p className="complaint">
        <strong>Chief complaint</strong>
        {encounter.chiefComplaint || "Not recorded"}
      </p>
      {Object.values(encounter.vitals || {}).some(
        (v) => v !== null && v !== "",
      ) ? (
        <div className="vitals">
          {Object.entries(encounter.vitals)
            .filter(([, v]) => v !== null && v !== "")
            .map(([k, v]) => (
              <div key={k}>
                <span>
                  {(
                    {
                      bloodPressure: "Blood pressure (mmHg)",
                      heartRate: "Heart rate (bpm)",
                      temperature: "Temperature (°F)",
                      oxygenSaturation: "SpO₂ (%)",
                      weight: "Weight (lb)",
                    } as Record<string, string>
                  )[k] || k}
                </span>
                <strong>{v}</strong>
              </div>
            ))}
        </div>
      ) : null}
      <div className="note-fields">
        {(
          [
            { key: "subjective", label: "Subjective", rows: 3 },
            { key: "objective", label: "Objective", rows: 3 },
            { key: "assessmentPlan", label: "Assessment & Plan", rows: 6 },
          ] as const
        ).map(({ key, label, rows }) => (
          <Field label={label} key={key}>
            <textarea
              value={note[key]}
              onChange={(e) => {
                onEditing();
                setNote({ ...note, [key]: e.target.value });
              }}
              rows={rows}
              maxLength={key === "assessmentPlan" ? 40960 : 20000}
              disabled={signed || saving}
              placeholder={`Enter ${label.toLowerCase()}…`}
            />
          </Field>
        ))}
      </div>
      {error ? <ErrorMessage message={error} /> : null}
      {signed ? (
        <div className="signed-record">
          <LockKeyhole size={18} />
          <div>
            Signed by {encounter.signedBy} on{" "}
            {encounter.signedAt ? displayDate(encounter.signedAt) : "—"}. This
            note is locked.
            <small className="mono">Signature {encounter.signatureHash}</small>
          </div>
        </div>
      ) : confirmSign ? (
        <div className="sign-confirm">
          <h3>Review and sign this encounter</h3>
          <p>
            Signing attests that you have reviewed this note. The signed note
            will be locked and cannot be edited.
          </p>
          <label className="confirmation-checkbox">
            <input
              type="checkbox"
              id="sign-attestation"
              checked={attested}
              onChange={(e) => setAttested(e.target.checked)}
            />
            I have reviewed all sections and confirm this note is complete.
          </label>
          <div className="modal-actions">
            <button className="button" onClick={() => setConfirmSign(false)}>
              Keep editing
            </button>
            <button
              className="button primary"
              id="final-sign"
              disabled={!attested || saving || !complete}
              onClick={() => save(true)}
            >
              Confirm and sign
            </button>
          </div>
        </div>
      ) : (
        <div className="modal-actions">
          <span className="muted small-text">
            Version {encounter.version} · Changes save when you choose Save
            draft.
          </span>
          <button className="button" disabled={saving} onClick={() => save()}>
            <Save size={16} />
            {saving ? "Saving…" : "Save draft"}
          </button>
          <button
            className="button primary"
            disabled={saving || !complete}
            onClick={() => setConfirmSign(true)}
          >
            <Check size={16} />
            Review & sign
          </button>
        </div>
      )}
      <ClinicalTextReview
        encounterId={encounter.id}
        version={encounter.version}
        dirty={dirty}
        saving={saving}
        hasNote={Object.values(savedNote).some((text) => text.trim())}
      />
    </div>
  );
}
