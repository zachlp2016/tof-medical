export interface Patient {
  id: string;
  mrn: string;
  firstName: string;
  lastName: string;
  name: string;
  dateOfBirth: string;
  age: number;
  sex: string;
  phone: string | null;
  email: string | null;
  status: string;
  allergies: string[];
  conditions: string[];
  medications: string[];
  lastVisit: string | null;
  avatarColor: string;
}
export interface Appointment {
  id: string;
  patientId: string;
  patientName: string;
  patientMrn: string;
  avatarColor: string;
  startTime: string;
  durationMinutes: number;
  type: string;
  status: string;
  clinician: string;
  room: string;
}
export interface Note {
  subjective: string;
  objective: string;
  assessmentPlan?: string;
  assessment?: string;
  plan?: string;
}
export interface Encounter {
  id: string;
  patientId: string;
  patientName: string;
  startedAt: string;
  type: string;
  status: string;
  clinician: string;
  chiefComplaint: string;
  note: Note;
  vitals: Record<string, string | number | null>;
  updatedAt: string;
  version: number;
  signedAt: string | null;
  signedBy: string | null;
  signatureHash: string | null;
}
export interface CareTask {
  id: string;
  patientId: string;
  patientName: string;
  title: string;
  priority: string;
  status: string;
  dueDate: string;
}
export interface Dashboard {
  today: string;
  stats: {
    appointmentsToday: number;
    checkedIn: number;
    openEncounters: number;
    pendingTasks: number;
    totalPatients: number;
  };
  appointments: Appointment[];
  recentPatients: Patient[];
  tasks: CareTask[];
}
export interface Chart {
  patient: Patient;
  appointments: Appointment[];
  encounters: Encounter[];
}
export interface AuditEvent {
  id: string;
  timestamp: string;
  actorId: string;
  action: string;
  resourceType: string;
  resourceId: string;
  outcome: string;
}
export interface Integration {
  service: string;
  status: string;
  mode: string;
  mcpEndpoint: string;
  protocolVersion: string;
  tools: { name: string; description: string }[];
  tenantId: string;
  actorId: string;
  scopes: string[];
  syntheticData: boolean;
  connectedToTof: boolean;
}
export type ReviewOperation = "deidentify" | "entities";
export interface ReviewModel {
  id: string;
  revision: string | null;
  servedModel?: string;
}
export interface AiOperationStatus {
  configured: boolean;
  ready: boolean;
  state: "awaiting-credentials" | "unverified" | "ready" | "unavailable";
  provider: string;
  location: "local" | "remote";
  model: ReviewModel | null;
  verifiedAt?: string;
  warnings: string[];
}
export interface ClinicalAiStatus {
  configured: boolean;
  ready: boolean;
  models: Partial<Record<ReviewOperation, ReviewModel>>;
  operations: Record<ReviewOperation, AiOperationStatus>;
  warnings: string[];
  reviewRequired: true;
}
export interface ClinicalReviewResult {
  encounterId: string;
  encounterVersion: number;
  operation: ReviewOperation;
  provider: string;
  location: "local" | "remote";
  redactedText?: string;
  entities: {
    text: string;
    label: string;
    start: number;
    end: number;
    confidence: number | null;
    assertion?: string;
  }[];
  model: ReviewModel;
  warnings: string[];
  durationMs: number;
  reviewRequired: true;
}
export type Page =
  | "Today"
  | "Patients"
  | "Schedule"
  | "Encounters"
  | "Care tasks"
  | "Audit trail"
  | "Connections";
