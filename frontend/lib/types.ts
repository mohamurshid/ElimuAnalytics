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

/**
 * What the API says happened when you asked for something to be removed.
 *
 * Two outcomes, and the difference matters to the person doing it: a record
 * with learner responses attached is withdrawn, because deleting it would
 * cascade to those responses and change ability estimates derived from them.
 * `detail` carries the server's explanation, which the interface shows rather
 * than paraphrasing.
 */
export type Removal = {
  deleted: boolean;
  deactivated: boolean;
  response_count: number;
  detail: string;
};

/** The answer to undoing a withdrawal. */
export type Restore = {
  restored: boolean;
  learners_restored: number;
  detail: string;
};

/** What one assessment cycle did. */
export type Assessment = {
  strand: string;
  learners: number;
  estimates_recorded: number;
  skipped_insufficient_evidence: number;
  minimum_responses: number;
  confident_responses: number;
  new_flags: number;
};

export type Item = {
  item_id: string;
  strand_id: string;
  question_text: string;
  difficulty_b: number | null;
  discrimination_a: number | null;
  is_active: boolean;
  response_count: number;
};

/** Which learner-item pairs already have a response, as "studentId:itemId". */
export type AnsweredPairs = {
  class_id: string;
  strand_id: string;
  answered: string[];
};

export type AssessmentReceipt = {
  batch_id: string;
  client_batch_id: string;
  class_id: string;
  strand_id: string;
  responses_recorded: number;
  duplicate: boolean;
  detail: string;
};

/** What a learner's device is allowed to know about an item. */
export type QuizItem = {
  item_id: string;
  question_text: string;
  options: string[];
  // There is deliberately no correct_option here, and no field for one on the
  // server's response model either. The device is never told the answer: a
  // client that can mark answers has necessarily been given the key, and a
  // key in the browser is a key a learner can read.
};

export type Quiz = {
  class_id: string;
  strand_id: string;
  strand: string;
  items: QuizItem[];
};

/**
 * What the grounding check concluded about one language of a report.
 *
 * `verbatim_quotes_verified` is the evidence: each entry was found character
 * for character in the curriculum chunk retrieved for this learner.
 * `verbatim_quotes_fabricated` is the opposite and the dangerous one - a span
 * in quotation marks that is NOT in the supplied curriculum looks like
 * evidence and a teacher has no way to tell.
 *
 * `vague_phrases_*` and `lexical_overlap` are recorded and never decide. The
 * vague lists are heuristics, and the Kiswahili half has not been validated by
 * a Kiswahili speaker, so a wrong entry must not be able to block a good
 * report from reaching a parent.
 */
export type ReportGrounding = {
  verdict: string;
  exportable: boolean;
  verbatim_quotes_verified: string[];
  verbatim_quotes_fabricated: string[];
  vague_phrases_en: string[];
  vague_phrases_sw: string[];
  lexical_overlap: number;
  words: number;
  truncated?: boolean;
  empty?: boolean;
};

/**
 * A generated diagnostic report, with the evidence that it was grounded.
 *
 * `exportable` is the server's decision, not a hint: it is true only when
 * every citation in BOTH languages was verified and neither generation was
 * truncated. A report sent home is only as good as the half the parent can
 * read, so the interface must not offer to send one that is false.
 */
export type Report = {
  report_id: string;
  student_id: string;
  strand_id: string | null;
  learner: string;
  content_en: string | null;
  content_sw: string | null;
  verdict: string | null;
  exportable: boolean;
  detail: string;
  top_similarity: number | null;
  chunk_source_rows: number[] | null;
  model: string | null;
  effort: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  thinking_tokens: number | null;
  cost_usd: number | null;
  grounding: Record<string, ReportGrounding> | null;
  generated_at: string | null;
};
