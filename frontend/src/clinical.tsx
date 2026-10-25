import { useEffect, useState } from "react";
import {
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Link2,
  Plus,
  Search,
} from "lucide-react";
import { api, displayDate, localDate, time, titleCase, useApi } from "./api";
import type {
  Appointment,
  CareTask,
  Chart,
  Dashboard,
  Encounter,
  Patient,
} from "./types";
import {
  ArrowLink,
  Avatar,
  Empty,
  ErrorMessage,
  Loading,
  PageHeading,
  Status,
} from "./ui";

type Shared = {
  revision: number;
  onPatient: (id: string) => void;
  onEncounter: (id: string) => void;
  onChange: () => void;
};
function AppointmentTable({
  appointments,
  patients = [],
  onPatient,
  checkIn,
  onChange,
}: {
  appointments: Appointment[];
  patients?: Patient[];
  onPatient?: (id: string) => void;
  checkIn?: boolean;
  onChange?: () => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  async function update(id: string) {
    setBusy(id);
    setError("");
    try {
      await api(`/appointments/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "checked-in" }),
      });
      onChange?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  if (!appointments.length)
    return (
      <Empty
        title="No appointments to show"
        detail="Appointments that match this view will appear here."
      />
    );
  return (
    <>
      {error ? <ErrorMessage message={error} /> : null}
      <div className="table-scroll">
        <table className="appointment-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Patient</th>
              <th>Visit</th>
              <th>Status</th>
              {checkIn ? (
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {appointments.map((a) => {
              const p = patients.find((p) => p.id === a.patientId);
              return (
                <tr key={a.id}>
                  <td className="time-cell">{time(a.startTime)}</td>
                  <td>
                    <div className="patient-cell">
                      <Avatar name={a.patientName} color={p?.avatarColor ?? a.avatarColor} />
                      <span>
                        {onPatient ? (
                          <button
                            className="patient-name"
                            onClick={() => onPatient(a.patientId)}
                          >
                            {a.patientName}
                          </button>
                        ) : (
                          <strong>{a.patientName}</strong>
                        )}
                        <small className="mono">{p?.mrn ?? a.patientMrn}</small>
                      </span>
                    </div>
                  </td>
                  <td>{a.type}</td>
                  <td>
                    <Status value={a.status} />
                  </td>
                  {checkIn ? (
                    <td>
                      {a.status === "scheduled" ? (
                        <button
                          className="text-button"
                          disabled={busy === a.id}
                          onClick={() => update(a.id)}
                        >
                          {busy === a.id ? "Updating…" : "Check in"}
                        </button>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
function TaskList({
  tasks,
  onChange,
  onPatient,
  compact = false,
}: {
  tasks: CareTask[];
  onChange: () => void;
  onPatient: (id: string) => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function toggle(task: CareTask) {
    setBusy(task.id);
    setError("");
    try {
      await api(`/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: task.status === "completed" ? "open" : "completed",
        }),
      });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      {error ? <ErrorMessage message={error} /> : null}
      {tasks.length ? (
        <div className={`task-list ${compact ? "compact" : ""}`}>
          {tasks.map((t) => (
            <div
              className={`task-row ${t.status === "completed" ? "completed" : ""}`}
              key={t.id}
            >
              <button
                className="task-check"
                aria-label={`${t.status === "completed" ? "Reopen" : "Complete"} task: ${t.title}`}
                disabled={busy === t.id}
                onClick={() => toggle(t)}
              >
                {t.status === "completed" ? <Check size={15} /> : null}
              </button>
              <div className="task-copy">
                <strong>{t.title}</strong>
                <button
                  className="patient-text"
                  onClick={() => onPatient(t.patientId)}
                >
                  {t.patientName}
                </button>
              </div>
              <div className="task-due">
                <span>
                  Due{" "}
                  {displayDate(t.dueDate, { month: "short", day: "numeric" })}
                </span>
                {!compact ? <Status value={t.priority} /> : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          title="You're all caught up"
          detail="There are no care tasks in this view."
        />
      )}
    </>
  );
}
export function Today({
  revision,
  onPatient,
  onEncounter: _,
  onChange,
  onNewEncounter,
  onSchedule,
  onTasks,
  onConnections,
}: Shared & {
  onNewEncounter: () => void;
  onSchedule: () => void;
  onTasks: () => void;
  onConnections: () => void;
}) {
  const { data, error, loading, reload } = useApi<Dashboard>(
    "/dashboard",
    revision,
  );
  const [filter, setFilter] = useState("all");
  if (loading) return <Loading />;
  if (error) return <ErrorMessage message={error} retry={reload} />;
  if (!data) return null;
  const appointments = data.appointments.filter(
    (a) =>
      filter === "all" ||
      (filter === "checked-in"
        ? a.status === "checked-in"
        : a.status === "scheduled"),
  );
  return (
    <>
      <PageHeading
        title="Your day, at a glance"
        description="A clear view of your practice. One patient at a time."
        action={
          <button className="button primary" onClick={onNewEncounter}>
            <Plus size={19} />
            New encounter
          </button>
        }
      />
      <h2 className="today-date">
        {displayDate(data.today, {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        })}
      </h2>
      <div className="stats-row">
        {[
          [data.stats.appointmentsToday, "Appointments"],
          [data.stats.checkedIn, "Checked in"],
          [data.stats.openEncounters, "Open encounters"],
          [data.stats.pendingTasks, "Care tasks"],
        ].map(([value, label]) => (
          <div className="stat" key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <div>
          <section className="panel schedule-panel">
            <div className="section-heading">
              <div>
                <h2>Today’s schedule</h2>
                <p>{data.stats.appointmentsToday} appointments</p>
              </div>
              <ArrowLink onClick={onSchedule}>View schedule</ArrowLink>
            </div>
            <div
              className="segmented schedule-tabs"
              aria-label="Filter appointments"
            >
              {[
                ["all", "All appointments"],
                ["checked-in", "Checked in"],
                ["upcoming", "Upcoming"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  className={filter === id ? "selected" : ""}
                  aria-pressed={filter === id}
                  onClick={() => setFilter(id)}
                >
                  {label}
                </button>
              ))}
            </div>
            <AppointmentTable
              appointments={appointments}
              patients={data.recentPatients}
              onPatient={onPatient}
            />
          </section>
          <section className="panel recent-panel">
            <h3>Recent patients</h3>
            {data.recentPatients.length ? (
              data.recentPatients.slice(0, 3).map((p) => (
                <div className="recent-row" key={p.id}>
                  <Avatar name={p.name} color={p.avatarColor} small />
                  <strong>{p.name}</strong>
                  <span className="mono">{p.mrn}</span>
                  <ArrowLink onClick={() => onPatient(p.id)}>
                    Open chart
                  </ArrowLink>
                </div>
              ))
            ) : (
              <Empty title="No patients yet" />
            )}
          </section>
        </div>
        <aside className="dashboard-aside">
          <section className="care-section">
            <div className="section-heading">
              <h2>Care tasks</h2>
              <ArrowLink onClick={onTasks}>View all</ArrowLink>
            </div>
            <TaskList
              tasks={data.tasks
                .filter((t) => t.status !== "completed")
                .slice(0, 4)}
              onChange={onChange}
              onPatient={onPatient}
              compact
            />
          </section>
          <button className="connection-prompt" onClick={onConnections}>
            <Link2 size={24} />
            <div>
              <h3>Connected care</h3>
              <p>Connect your clinical workspace to TOF.</p>
            </div>
            <span>
              Set up connection <ChevronRight size={14} />
            </span>
          </button>
        </aside>
      </div>
    </>
  );
}
export function Patients({
  revision,
  onPatient,
  onAdd,
}: {
  revision: number;
  onPatient: (id: string) => void;
  onAdd: () => void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(handle);
  }, [search]);
  const { data, error, loading, reload } = useApi<Patient[]>(
    `/patients?search=${encodeURIComponent(query)}`,
    revision,
  );
  const list = data || [];
  return (
    <>
      <PageHeading
        title="Patients"
        description="A complete picture of every patient in your care."
        action={
          <button className="button primary" onClick={onAdd}>
            <Plus size={18} />
            Add patient
          </button>
        }
      />
      <div className="toolbar">
        <div className="search-input">
          <Search size={18} />
          <input
            aria-label="Search patients"
            placeholder="Search by name or MRN"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="muted">
          {list.length} patients
          {list.length === 100 ? " (first 100 matches)" : ""}
        </span>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : list.length ? (
        <section className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Patient</th>
                <th>MRN</th>
                <th>Date of birth</th>
                <th>Sex</th>
                <th>Last visit</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id}>
                  <td>
                    <button
                      className="patient-cell"
                      onClick={() => onPatient(p.id)}
                    >
                      <Avatar name={p.name} color={p.avatarColor} />
                      <strong>{p.name}</strong>
                    </button>
                  </td>
                  <td className="mono">{p.mrn}</td>
                  <td>
                    {displayDate(p.dateOfBirth)}{" "}
                    <span className="muted">({p.age})</span>
                  </td>
                  <td>{titleCase(p.sex)}</td>
                  <td>
                    {p.lastVisit ? displayDate(p.lastVisit) : "No visits"}
                  </td>
                  <td>
                    <ArrowLink onClick={() => onPatient(p.id)}>
                      Open chart
                    </ArrowLink>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <Empty
          title={search ? "No matching patients" : "No patients yet"}
          detail={
            search
              ? "Try a different name or MRN."
              : "Add a patient to start a clinical record."
          }
        />
      )}
    </>
  );
}
export function PatientChart({
  id,
  revision,
  onBack,
  onNewEncounter,
  onEncounter,
}: {
  id: string;
  revision: number;
  onBack: () => void;
  onNewEncounter: () => void;
  onEncounter: (id: string) => void;
}) {
  const { data, error, loading, reload } = useApi<Chart>(
    `/patients/${id}`,
    revision,
  );
  if (loading) return <Loading />;
  if (error) return <ErrorMessage message={error} retry={reload} />;
  if (!data) return null;
  const p = data.patient;
  return (
    <>
      <button className="back-link" onClick={onBack}>
        <ChevronLeft size={16} />
        All patients
      </button>
      <PageHeading
        title={p.name}
        description={`${p.mrn} · ${p.age} years · ${titleCase(p.sex)} · Born ${displayDate(p.dateOfBirth)}`}
        action={
          <button className="button primary" onClick={onNewEncounter}>
            <Plus size={18} />
            New encounter
          </button>
        }
      />
      <div className="chart-contact">
        <span>
          <strong>Phone</strong>
          {p.phone || "Not recorded"}
        </span>
        <span>
          <strong>Email</strong>
          {p.email || "Not recorded"}
        </span>
        <span>
          <strong>Status</strong>
          {titleCase(p.status)}
        </span>
      </div>
      <div className="clinical-summary">
        <section>
          <h2>Allergies</h2>
          {p.allergies.length ? (
            <ul>
              {p.allergies.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : (
            <p className="unknown">Allergy status unknown</p>
          )}
        </section>
        <section>
          <h2>Conditions</h2>
          {p.conditions.length ? (
            <ul>
              {p.conditions.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No conditions recorded</p>
          )}
        </section>
        <section>
          <h2>Medications</h2>
          {p.medications.length ? (
            <ul>
              {p.medications.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No medications recorded</p>
          )}
        </section>
      </div>
      <section className="panel">
        <div className="section-heading">
          <h2>Encounters</h2>
          <span className="muted">{data.encounters.length} records</span>
        </div>
        <EncounterTable
          encounters={data.encounters}
          onEncounter={onEncounter}
        />
      </section>
      <section className="panel section-gap">
        <div className="section-heading">
          <h2>Appointments</h2>
        </div>
        <AppointmentTable appointments={data.appointments} patients={[p]} />
      </section>
    </>
  );
}
export function Schedule({
  revision,
  onPatient,
  onNewAppointment,
  onChange,
}: {
  revision: number;
  onPatient: (id: string) => void;
  onNewAppointment: (date: string) => void;
  onChange: () => void;
}) {
  const [date, setDate] = useState(localDate);
  const [filter, setFilter] = useState("all");
  const { data, error, loading, reload } = useApi<Appointment[]>(
    `/appointments?date=${date}`,
    revision,
  );
  function move(days: number) {
    const d = new Date(`${date}T12:00:00`);
    d.setDate(d.getDate() + days);
    setDate(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
    );
  }
  return (
    <>
      <PageHeading
        title="Schedule"
        description="Make space for better care."
        action={
          <button
            className="button primary"
            onClick={() => onNewAppointment(date)}
          >
            <Plus size={18} />
            New appointment
          </button>
        }
      />
      <div className="toolbar">
        <div className="date-controls">
          <button
            className="icon-button"
            aria-label="Previous day"
            onClick={() => move(-1)}
          >
            <ChevronLeft size={19} />
          </button>
          <label className="date-input">
            <CalendarDays size={18} />
            <input
              aria-label="Appointment date"
              type="date"
              value={date}
              onChange={(e) => {
                if (e.target.value) setDate(e.target.value);
              }}
            />
          </label>
          <button
            className="icon-button"
            aria-label="Next day"
            onClick={() => move(1)}
          >
            <ChevronRight size={19} />
          </button>
          <button className="button" onClick={() => setDate(localDate())}>
            Today
          </button>
        </div>
        <select
          aria-label="Appointment status"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All appointments</option>
          <option value="scheduled">Scheduled</option>
          <option value="checked-in">Checked in</option>
          <option value="in-progress">In progress</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : (
        <section className="panel">
          <div className="section-heading">
            <h2>
              {displayDate(date, {
                weekday: "long",
                month: "long",
                day: "numeric",
              })}
            </h2>
            <span className="muted">{data?.length || 0} appointments</span>
          </div>
          <AppointmentTable
            appointments={(data || []).filter(
              (a) => filter === "all" || a.status === filter,
            )}
            onPatient={onPatient}
            checkIn
            onChange={onChange}
          />
        </section>
      )}
    </>
  );
}
function EncounterTable({
  encounters,
  onEncounter,
}: {
  encounters: Encounter[];
  onEncounter: (id: string) => void;
}) {
  return encounters.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Patient</th>
            <th>Visit</th>
            <th>Date</th>
            <th>Status</th>
            <th>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {encounters.map((e) => (
            <tr key={e.id}>
              <td>
                <strong>{e.patientName}</strong>
                <small className="table-subtext">{e.chiefComplaint}</small>
              </td>
              <td>{e.type}</td>
              <td>{displayDate(e.startedAt)}</td>
              <td>
                <Status value={e.status} />
              </td>
              <td>
                <ArrowLink onClick={() => onEncounter(e.id)}>
                  {e.status === "signed" ? "View note" : "Open note"}
                </ArrowLink>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty
      title="No encounters yet"
      detail="Start an encounter to document a patient visit."
    />
  );
}
export function Encounters({
  revision,
  onEncounter,
  onNew,
}: {
  revision: number;
  onEncounter: (id: string) => void;
  onNew: () => void;
}) {
  const { data, error, loading, reload } = useApi<Encounter[]>(
    "/encounters",
    revision,
  );
  const [filter, setFilter] = useState("all");
  return (
    <>
      <PageHeading
        title="Encounters"
        description="Thoughtful documentation. A clear continuity of care."
        action={
          <button className="button primary" onClick={onNew}>
            <Plus size={18} />
            New encounter
          </button>
        }
      />
      <div className="toolbar">
        <div className="segmented">
          {["all", "draft", "signed"].map((v) => (
            <button
              key={v}
              className={filter === v ? "selected" : ""}
              aria-pressed={filter === v}
              onClick={() => setFilter(v)}
            >
              {v === "all" ? "All encounters" : titleCase(v)}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : (
        <section className="panel">
          <EncounterTable
            encounters={(data || []).filter(
              (e) => filter === "all" || e.status === filter,
            )}
            onEncounter={onEncounter}
          />
        </section>
      )}
    </>
  );
}
export function Tasks({
  revision,
  onChange,
  onPatient,
}: {
  revision: number;
  onChange: () => void;
  onPatient: (id: string) => void;
}) {
  const { data, error, loading, reload } = useApi<CareTask[]>(
    "/tasks",
    revision,
  );
  const [filter, setFilter] = useState("open");
  return (
    <>
      <PageHeading
        title="Care tasks"
        description="The next steps that keep care moving."
      />
      <div className="toolbar">
        <div className="segmented">
          {["open", "completed", "all"].map((v) => (
            <button
              className={filter === v ? "selected" : ""}
              key={v}
              aria-pressed={filter === v}
              onClick={() => setFilter(v)}
            >
              {titleCase(v)}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorMessage message={error} retry={reload} />
      ) : (
        <section className="panel tasks-panel">
          <TaskList
            tasks={(data || []).filter(
              (t) => filter === "all" || t.status === filter,
            )}
            onChange={onChange}
            onPatient={onPatient}
          />
        </section>
      )}
    </>
  );
}
