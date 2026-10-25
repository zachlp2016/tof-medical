import { useState } from "react";
import {
  CalendarDays,
  CheckSquare,
  ClipboardList,
  FileText,
  History,
  Link2,
  Menu,
  Plus,
  Users,
  X,
} from "lucide-react";
import type { Page, Patient, Encounter, Integration } from "./types";
import { useApi } from "./api";
import {
  Today,
  Patients,
  PatientChart,
  Schedule,
  Encounters,
  Tasks,
} from "./clinical";
import { Audit, Connections } from "./connections";
import {
  AppointmentForm,
  EncounterEditor,
  EncounterForm,
  PatientForm,
} from "./workflows";
const NAV = [
  { label: "Today", icon: CalendarDays },
  { label: "Patients", icon: Users },
  { label: "Schedule", icon: CalendarDays },
  { label: "Encounters", icon: FileText },
  { label: "Care tasks", icon: CheckSquare },
  { label: "Audit trail", icon: History },
  { label: "Connections", icon: Link2 },
] as const;
export default function App() {
  const [page, setPage] = useState<Page>("Today");
  const [patientId, setPatientId] = useState<string>();
  const [revision, setRevision] = useState(0);
  const [menu, setMenu] = useState(false);
  const [modal, setModal] = useState<"patient" | "encounter" | "appointment">();
  const [encounterId, setEncounterId] = useState<string>();
  const [appointmentDate, setAppointmentDate] = useState("");
  const { data: integration } = useApi<Integration>("/integration", revision);
  const refresh = () => setRevision((v) => v + 1);
  function navigate(next: Page) {
    setPage(next);
    setPatientId(undefined);
    setMenu(false);
  }
  function openPatient(id: string) {
    setPatientId(id);
    setPage("Patients");
    setMenu(false);
  }
  function patientCreated(p: Patient) {
    setModal(undefined);
    refresh();
    openPatient(p.id);
  }
  function encounterCreated(e: Encounter) {
    setModal(undefined);
    refresh();
    setEncounterId(e.id);
  }
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <aside className={`sidebar ${menu ? "is-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">TOF</span>
          <span>
            <strong>TOF</strong> Clinical
          </span>
          <button
            className="icon-button mobile-close"
            aria-label="Close navigation"
            onClick={() => setMenu(false)}
          >
            <X size={20} />
          </button>
        </div>
        <nav aria-label="Main navigation">
          {NAV.map(({ label, icon: Icon }, i) => (
            <button
              key={label}
              className={`nav-item ${page === label ? "active" : ""} ${i === 5 ? "nav-separated" : ""}`}
              aria-current={page === label ? "page" : undefined}
              onClick={() => navigate(label)}
            >
              <Icon size={21} strokeWidth={1.7} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span>
            {integration?.mode === "production"
              ? "Clinical workspace"
              : "Development workspace"}
          </span>
          <span>
            {integration
              ? integration.syntheticData
                ? "Synthetic patient data"
                : "Configured patient data"
              : "Checking workspace status…"}
          </span>
        </div>
      </aside>
      {menu ? (
        <button
          className="nav-scrim"
          aria-label="Close navigation"
          onClick={() => setMenu(false)}
        />
      ) : null}
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMenu(true)}
            >
              <Menu size={21} />
            </button>
            <span>Clinical</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{page}</strong>
            {patientId ? (
              <>
                <span className="breadcrumb-slash">/</span>
                <span>Patient chart</span>
              </>
            ) : null}
          </div>
          <div className="workspace-identity">
            <span>Family medicine</span>
            <span
              className="profile-avatar"
              aria-label="TOF Clinical workspace"
            >
              TC
            </span>
          </div>
        </header>
        {integration?.syntheticData ? (
          <div className="environment-banner">
            <span className="environment-dot" />
            Development workspace · Synthetic patient data only
          </div>
        ) : null}
        <main id="main-content" tabIndex={-1}>
          {page === "Today" ? (
            <Today
              revision={revision}
              onPatient={openPatient}
              onEncounter={setEncounterId}
              onChange={refresh}
              onNewEncounter={() => setModal("encounter")}
              onSchedule={() => navigate("Schedule")}
              onTasks={() => navigate("Care tasks")}
              onConnections={() => navigate("Connections")}
            />
          ) : page === "Patients" ? (
            patientId ? (
              <PatientChart
                id={patientId}
                revision={revision}
                onBack={() => setPatientId(undefined)}
                onNewEncounter={() => setModal("encounter")}
                onEncounter={setEncounterId}
              />
            ) : (
              <Patients
                revision={revision}
                onPatient={openPatient}
                onAdd={() => setModal("patient")}
              />
            )
          ) : page === "Schedule" ? (
            <Schedule
              revision={revision}
              onPatient={openPatient}
              onChange={refresh}
              onNewAppointment={(date) => {
                setAppointmentDate(date);
                setModal("appointment");
              }}
            />
          ) : page === "Encounters" ? (
            <Encounters
              revision={revision}
              onEncounter={setEncounterId}
              onNew={() => setModal("encounter")}
            />
          ) : page === "Care tasks" ? (
            <Tasks
              revision={revision}
              onChange={refresh}
              onPatient={openPatient}
            />
          ) : page === "Audit trail" ? (
            <Audit revision={revision} />
          ) : (
            <Connections revision={revision} onSessionChange={refresh} />
          )}
        </main>
        <footer className="workspace-footer">
          <ClipboardList size={13} />
          <span>TOF Clinical</span>
          <span className="footer-divider">·</span>
          <span>Care, connected.</span>
          <button onClick={() => navigate("Connections")}>
            Connection settings <Plus size={11} />
          </button>
        </footer>
      </div>
      {modal === "patient" ? (
        <PatientForm
          onClose={() => setModal(undefined)}
          onCreated={patientCreated}
        />
      ) : modal === "encounter" ? (
        <EncounterForm
          patientId={patientId}
          onClose={() => setModal(undefined)}
          onCreated={encounterCreated}
        />
      ) : modal === "appointment" ? (
        <AppointmentForm
          date={appointmentDate}
          onClose={() => setModal(undefined)}
          onCreated={() => {
            setModal(undefined);
            refresh();
          }}
        />
      ) : null}
      {encounterId ? (
        <EncounterEditor
          id={encounterId}
          onClose={() => setEncounterId(undefined)}
          onSaved={refresh}
        />
      ) : null}
    </div>
  );
}
