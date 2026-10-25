import type { Note } from "./types";

export interface EditorNote {
  subjective: string;
  objective: string;
  assessmentPlan: string;
}

/** Present legacy notes without modifying or splitting their original text. */
export function normalizeNote(note: Note): EditorNote {
  let assessmentPlan = note.assessmentPlan;
  if (assessmentPlan === undefined) {
    const assessment = note.assessment ?? "";
    const plan = note.plan ?? "";
    assessmentPlan =
      assessment.trim() || plan.trim()
        ? [
            assessment ? `Assessment:\n${assessment}` : "",
            plan ? `Plan:\n${plan}` : "",
          ]
            .filter(Boolean)
            .join("\n\n")
        : "";
  }
  return {
    subjective: note.subjective,
    objective: note.objective,
    assessmentPlan,
  };
}
