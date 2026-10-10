/**
 * The shapes the backend returns.
 *
 * Written by hand against the FastAPI response models rather than generated,
 * because there are few of them and a generator is another thing to keep
 * running. If they drift, `npm run typecheck` is where it shows up.
 *
 * The important one is `DiagnosticCell.theta`, which is `number | null`. That
 * null is not an error case or a missing value: it is the system declining to
 * estimate a learner's ability from too few answers. Typing it as nullable
 * means the compiler refuses to let a component render it without deciding
 * what to show instead.
 */

export type Role = "teacher" | "school_admin" | "system_admin";

export type LoginResponse = {
  access_token: string;
  token_type: string;
  role: Role;
  name: string;
};

export type Profile = {
  teacher_id: string;
  name: string;
  email: string;
  role: Role;
};

export type Strand = {
  strand_id: string;
  name: string;
  level: string;
  active_items: number;
  calibrated_items: number;
};

/** Three states, not two. A blank cell reads as a bug; this does not. */
export type CellStatus = "estimated" | "provisional" | "insufficient_evidence";

export type DiagnosticCell = {
  strand_id: string;
  strand: string;
  theta: number | null;
  tier: string | null;
  answered: number;
  status: CellStatus;
  message: string;
};

export type LearnerDiagnostics = {
  student_id: string;
  name: string;
  is_active: boolean;
  cells: DiagnosticCell[];
};

export type Heatmap = {
  class_id: string;
  grade: string;
  name: string;
  strands: Strand[];
  learners: LearnerDiagnostics[];
  minimum_responses: number;
  confident_responses: number;
};

export type Classroom = {
  class_id: string;
  grade: string;
  name: string;
  is_active: boolean;
  student_count: number;
};

export type Student = {
  student_id: string;
  name: string;
  class_id: string;
  is_active: boolean;
  response_count: number;
};

export type Flag = {
  flag_id: string;
  student_id: string;
  learner: string;
  class_id: string;
  strand_id: string;
  strand: string;
  severity: string;
  flagged_at: string | null;
};
