// Core data types for the tutoring system

// ----------------------------------------------------------------------------
// Document kinds and chunk kinds
// ----------------------------------------------------------------------------

export type DocumentKind =
  | 'manifest'
  | 'syllabus'
  | 'lesson'
  | 'concept'
  | 'assignment'
  | 'session_log'
  | 'state'
  | 'config';

export type ChunkKind =
  | 'summary'
  | 'overview'
  | 'definition'
  | 'theorem'
  | 'proof'
  | 'example'
  | 'exercise'
  | 'misconception'
  | 'reflection'
  | 'faq'
  | 'objective'
  | 'motivation';

// ----------------------------------------------------------------------------
// Tutor and Student profiles
// ----------------------------------------------------------------------------

export interface TutorConfig {
  name: string;
  persona: {
    style: string;
    tone: string;
    role: string;
    specialization: string[];
  };
  pedagogy: {
    defaultStructure: string[];
    emphasize: string[];
    avoid: string[];
  };
  adaptationRules: {
    askDiagnosticQuestions: boolean;
    slowDownOnConfusion: boolean;
    revisitPrerequisitesIfNeeded: boolean;
    weaveInMlConnections: string; // 'always' | 'occasionally' | 'never'
  };
}

export interface StudentProfile {
  studentId: string;
  displayName: string;
  background: {
    mathLevel: string;
    priorCourses: string[];
    strengths: string[];
    weakAreas: string[];
  };
  preferences: {
    pace: 'slow' | 'moderate' | 'fast';
    rigor: 'low' | 'medium' | 'high';
    examplesBeforeProofs: boolean;
    exercisesPerLesson: number;
  };
  goals: string[];
}

// ----------------------------------------------------------------------------
// Course manifest and syllabus
// ----------------------------------------------------------------------------

export interface CourseManifest {
  id: string;
  title: string;
  subject: string;
  status: 'active' | 'paused' | 'completed';
  createdAt: string;
  updatedAt: string;
  currentLessonId?: string;
  currentUnit?: string;
  syllabusVersion: number;
  courseGoals: string[];
  policies: {
    adaptationMode: string;
    retrievalMode: 'lexical' | 'semantic' | 'hybrid';
    sessionConsolidation: 'required' | 'optional' | 'none';
  };
}

export interface SyllabusUnit {
  title: string;
  topics: string[];
}

export interface Syllabus {
  id: string;
  subject: string;
  version: number;
  generatedAt: string;
  units: SyllabusUnit[];
}

// ----------------------------------------------------------------------------
// Lessons and Concepts
// ----------------------------------------------------------------------------

export interface LessonFrontmatter {
  id: string;
  title: string;
  lessonNumber: number;
  status: 'draft' | 'completed' | 'reviewed';
  unit: string;
  concepts: string[];
  prerequisites: string[];
  objectives: string[];
  assignedWork?: string[];
}

export interface ConceptFrontmatter {
  id: string;
  title: string;
  aliases?: string[];
  tags: string[];
  prerequisites: string[];
  related: string[];
}

export interface MasteryRecord {
  mastery: number; // 0-1
  confidence: 'low' | 'medium' | 'high';
  lastSeen: string;
  evidence: string[];
  concerns?: string[];
}

export interface MasteryState {
  concepts: Record<string, MasteryRecord>;
}

// ----------------------------------------------------------------------------
// Session and Transcript
// ----------------------------------------------------------------------------

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export interface TranscriptMessage {
  role: MessageRole;
  content: string;
  timestamp: string;
  toolName?: string;
  toolResult?: unknown;
}

export interface SessionLog {
  id: string;
  date: string;
  title: string;
  summary: string;
}

export interface SessionState {
  sessionId: string;
  courseId: string;
  startTime: string;
  messages: TranscriptMessage[];
  agenda: string[];
  openQuestions: string[];
}

// ----------------------------------------------------------------------------
// Retrieval and Indexing
// ----------------------------------------------------------------------------

export interface DocumentEntry {
  id: string;
  path: string;
  kind: DocumentKind;
  title?: string;
  lessonId?: string;
  conceptId?: string;
  unit?: string;
  createdAt: string;
  updatedAt: string;
  checksum: string;
}

export interface ChunkEntry {
  id: string;
  documentId: string;
  chunkKind: ChunkKind;
  ordinal: number;
  heading?: string;
  content: string;
  tokenEstimate: number;
}

export interface ChunkTag {
  chunkId: string;
  tag: string;
}

export interface ConceptEdge {
  sourceConceptId: string;
  relation: 'prerequisite' | 'related' | 'part-of';
  targetConceptId: string;
}

export interface SearchResult {
  chunkId: string;
  documentId: string;
  path: string;
  score: number;
  chunkKind: ChunkKind;
  heading?: string;
  contentPreview: string;
  tags: string[];
}

export interface RetrievalFilters {
  kinds?: DocumentKind[];
  lessonId?: string;
  conceptIds?: string[];
  tags?: string[];
  since?: string;
}

// ----------------------------------------------------------------------------
// Event Logging
// ----------------------------------------------------------------------------

export type EventType =
  | 'course_initialized'
  | 'syllabus_generated'
  | 'lesson_opened'
  | 'turn_completed'
  | 'retrieval_executed'
  | 'session_note_added'
  | 'misconception_recorded'
  | 'assignment_created'
  | 'session_consolidated'
  | 'workspace_reindexed';

export interface EventLog {
  id: string;
  eventType: EventType;
  createdAt: string;
  payloadJson: string;
}

// ----------------------------------------------------------------------------
// Tool Definitions (for model)
// ----------------------------------------------------------------------------

export type ToolInput = Record<string, unknown>;

export interface ToolSpec {
  name: string;
  description: string;
  inputSchema: {
    type: 'object';
    properties: Record<string, { type: string; description: string }>;
    required?: string[];
  };
}

// ----------------------------------------------------------------------------
// Session Consolidation Outputs
// ----------------------------------------------------------------------------

export interface MisconceptionRecord {
  conceptId: string;
  text: string;
  severity: 'low' | 'medium' | 'high';
}

export interface MasteryUpdate {
  conceptId: string;
  delta: number;
  rationale: string;
}

export interface Assignment {
  title: string;
  body: string;
}

export interface SessionSummary {
  title: string;
  date: string;
  summary: string;
  conceptsCovered: string[];
  misconceptions: MisconceptionRecord[];
  masteryUpdates: MasteryUpdate[];
  nextAgenda: string[];
  assignments: Assignment[];
}

// ----------------------------------------------------------------------------
// Model Adapter
// ----------------------------------------------------------------------------

export interface GenerateRequest {
  messages: Array<{
    role: MessageRole;
    content: string;
    name?: string;
  }>;
  tools?: ToolSpec[];
  responseFormat?: 'text' | 'json';
  temperature?: number;
}

export interface GenerateResult {
  text?: string;
  toolCalls?: Array<{
    id: string;
    name: string;
    argumentsJson: string;
  }>;
  raw?: unknown;
}

export interface ModelAdapter {
  generate(request: GenerateRequest): Promise<GenerateResult>;
  stream?(): never; // TODO: implement streaming later
}

// ----------------------------------------------------------------------------
// Intent Classification
// ----------------------------------------------------------------------------

export type MessageIntent =
  | 'lesson_progression'
  | 'clarification_question'
  | 'proof_help'
  | 'exercise_attempt'
  | 'meta_course_change'
  | 'review_request'
  | 'search_request'
  | 'administrative';

// ----------------------------------------------------------------------------
// Tutor Contract (System Instructions)
// ----------------------------------------------------------------------------

export interface TutorContract {
  identity: {
    name: string;
    role: string;
  };
  style: {
    rigorLevel: number; // 1-5
    formality: 'formal' | 'semi-formal' | 'casual';
    leadWith: ('theory' | 'examples' | 'intuition')[];
  };
  teachingMethod: {
    emphasizeProofs: boolean;
    useAnalogies: boolean;
    adaptToPace: boolean;
    maintainContinuity: boolean;
  };
  boundaries: {
    maxAnswerLength?: number;
    alwaysEncourageQuestions: boolean;
    neverGiveFullSolutions?: boolean;
  };
}
