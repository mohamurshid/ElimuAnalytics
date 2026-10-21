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
  /** The school this account belongs to - the boundary of everything it sees. */
  school: string;
};

export type Strand = {
  strand_id: string;
  name: string;
  level: string;
  /** Approved questions: what a quiz can be given from. */
  active_items: number;
  calibrated_items: number;
  /** Waiting on a teacher (drafts) or a head teacher (reported). */
  draft_items: number;
  reported_items: number;
  /** The grade of the curriculum design it comes from; null before the catalogue. */
  grade: string | null;
  learning_area: string | null;
  curriculum_key: string | null;
};

/** The curriculum catalogue: what a class can be assessed on. */
export type CatalogueSubStrand = {
  key: string;
  number: string;
  name: string;
  chunks: number;
};

export type CatalogueStrand = {
  name: string;
  sub_strands: CatalogueSubStrand[];
};

export type CatalogueArea = {
  learning_area: string;
  language: string;
  available: boolean;
  strands: CatalogueStrand[];
};

export type Catalogue = {
  grades: { grade: string; learning_areas: CatalogueArea[] }[];
  unplaced_rows: number;
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

/** Where a question is in its life; see backend/app/item_status.py. */
export type ItemStatus = "draft" | "approved" | "reported" | "rejected" | "retired";

/** A teacher's view of a question, key and mark scheme included. Never the
 *  learner's: the quiz endpoint returns QuizItem, which has neither. */
export type Item = {
  item_id: string;
  strand_id: string;
  question_text: string;
  options: string[] | null;
  correct_option: number | null;
  rationale: string | null;
  /** Aligned with options; null at the key. */
  misconceptions: (string | null)[] | null;
  curriculum_excerpt: string | null;
  status: ItemStatus;
  source: "teacher" | "ai";
  version: number;
  previous_item_id: string | null;
  report_reason: string | null;
  difficulty_b: number | null;
  discrimination_a: number | null;
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

/** A saved quiz: the same questions on the print sheet, the marking grid
 *  and the device. Like Quiz, it carries no key. */
export type QuizSet = Quiz & {
  quiz_id: string;
  mode: "device" | "paper";
  created_at: string | null;
  /** Each item's number in the quiz as made - unchanged when one is withdrawn,
   *  so column 4 of the grid is still question 4 on the printed sheet. */
  numbers: number[];
  /** Chosen when it was made, since reported or retired, so left out. */
  withdrawn: number;
};

export type QuizSummary = {
  quiz_id: string;
  strand_id: string;
  strand: string;
  mode: "device" | "paper";
  questions: number;
  created_at: string | null;
};

/** One request to write draft questions, and what came of it. */
export type GenerationRun = {
  run_id: string;
  strand_id: string;
  status: "pending" | "ready" | "failed";
  requested: number;
  produced: number;
  dropped: { question: string; problems: string[] }[];
  error: string | null;
  item_ids: string[];
  remaining_today: number;
  cost_usd: number | null;
  duration_ms: number | null;
};

export type StrandGeneration = {
  remaining_today: number;
  per_run: number;
  running: GenerationRun | null;
  last: GenerationRun | null;
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
  /** pending | ready | failed. The row exists before its content does. */
  status: string;
  /** Why a failed report failed, in a sentence. Null unless status is failed. */
  error: string | null;
  duration_ms: number | null;
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

/** A teacher at the school, as a head teacher's staff list shows them. */
export type StaffMember = {
  teacher_id: string;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
  /** "active": has a password; "invited": waiting to use a setup code. */
  status: "active" | "invited" | "deactivated";
  setup_code_expires_at: string | null;
  is_you: boolean;
};

/** Returned once, when a code is made; only its hash is stored. */
export type StaffWithCode = StaffMember & { setup_code: string };
