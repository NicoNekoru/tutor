import path from 'path';
import * as yaml from 'yaml';
import { v4 as uuidv4 } from 'uuid';
import {
  GenerateRequest,
  GenerateResult,
  MessageIntent,
  TutorContract,
  StudentProfile,
  CourseManifest,
  SessionSummary,
  SearchResult,
  RetrievalFilters,
  ModelAdapter,
} from '../schemas/types';
import { RetrievalEngine } from '../retrieval/RetrievalEngine';
import { WorkspaceManager } from '../workspace/WorkspaceManager';
import { SQLiteDatabase } from '../indexer/Database';

// Intent classifier (simple rule-based for now)
export function classifyIntent(message: string): MessageIntent {
  const lower = message.toLowerCase();

  if (lower.includes('next') || lower.includes('move on') || lower.includes('continue')) {
    return 'lesson_progression';
  }
  if (lower.includes('example') || lower.includes('illustration') || lower.includes('show me')) {
    return 'clarification_question';
  }
  if (lower.includes('proof') || lower.includes('prove') || lower.includes('why is')) {
    return 'proof_help';
  }
  if (lower.includes('exercise') || lower.includes('problem') || lower.includes('homework')) {
    return 'exercise_attempt';
  }
  if (lower.includes('change') || lower.includes('setting') || lower.includes('prefer')) {
    return 'meta_course_change';
  }
  if (lower.includes('review') || lower.includes('recap') || lower.includes('again')) {
    return 'review_request';
  }
  if (lower.includes('search') || lower.includes('find') || lower.includes('look up')) {
    return 'search_request';
  }

  return 'clarification_question'; // default
}

// Build tutor contract from tutor.yaml
export function buildTutorContract(tutorConfig: Record<string, any>): TutorContract {
  return {
    identity: {
      name: tutorConfig.name || 'Tutor',
      role: tutorConfig.persona?.role || 'tutor',
    },
    style: {
      rigorLevel: 5,
      formality: tutorConfig.persona?.tone?.includes('formal') ? 'formal' : 'semi-formal',
      leadWith: ['theory', 'examples'],
    },
    teachingMethod: {
      emphasizeProofs: tutorConfig.pedagogy?.emphasize?.includes('proof techniques') ?? false,
      useAnalogies: true,
      adaptToPace: tutorConfig.adaptationRules?.slowDownOnConfusion ?? true,
      maintainContinuity: true,
    },
    boundaries: {
      alwaysEncourageQuestions: true,
    },
  };
}

export class Orchestrator {
  private modelAdapter: ModelAdapter;
  private retrieval: RetrievalEngine;
  private ws: WorkspaceManager;
  private db: SQLiteDatabase;
  private tutorContract: TutorContract | null = null;
  private studentProfile: StudentProfile | null = null;
  private courseManifest: CourseManifest | null = null;
  private sessionMessages: Array<{ role: string; content: string }> = [];

  constructor(
    modelAdapter: ModelAdapter,
    retrieval: RetrievalEngine,
    ws: WorkspaceManager,
    db: SQLiteDatabase
  ) {
    this.modelAdapter = modelAdapter;
    this.retrieval = retrieval;
    this.ws = ws;
    this.db = db;
  }

  async initializeSession(): Promise<void> {
    await this.loadCourseState();
  }

  private async loadCourseState(): Promise<void> {
    const courseRoot = this.ws.getCourseRoot();

    // Read tutor config
    const tutorContent = await this.ws.readFile(path.join('configs', 'tutor.yaml'));
    this.tutorContract = buildTutorContract(yaml.parse(tutorContent));

    // Read student profile
    const studentContent = await this.ws.readFile(path.join('configs', 'student.yaml'));
    this.studentProfile = yaml.parse(studentContent);

    // Read manifest
    const manifestContent = await this.ws.readFile('manifest.yaml');
    this.courseManifest = yaml.parse(manifestContent);
  }

  async processTurn(userMessage: string): Promise<{ response: string; retrievedContext: SearchResult[]; toolCalls?: any[] }> {
    // Track message
    this.sessionMessages.push({ role: 'user', content: userMessage });

    // 1. Classify intent
    const intent = classifyIntent(userMessage);

    // 2. Determine context need
    const retrievalPlan = this.buildRetrievalPlan(intent, userMessage);

    // 3. Retrieve relevant artifacts
    const retrievedChunks = this.executeRetrieval(retrievalPlan);

    // 4. Assemble model context
    const request = this.assembleRequest(userMessage, retrievedChunks);

    // 5. Call model
    const result = await this.modelAdapter.generate(request);

    // 6. Track response
    const responseText = result.text || '';
    this.sessionMessages.push({ role: 'assistant', content: responseText });

    // 7. Write transcript
    await this.ws.writeTranscriptEntry({ role: 'user', content: userMessage });
    await this.ws.writeTranscriptEntry({ role: 'assistant', content: responseText });

    // 8. Log turn event
    this.logEvent('turn_completed', {
      intent,
      userMessage: userMessage.substring(0, 100),
      retrievedChunkCount: retrievedChunks.length,
      modelOutputLength: responseText.length,
    });

    return {
      response: responseText,
      retrievedContext: retrievedChunks,
      toolCalls: result.toolCalls,
    };
  }

  private buildRetrievalPlan(intent: MessageIntent, query: string): {
    query: string;
    filters: RetrievalFilters;
    topK: number;
  } {
    const filters: RetrievalFilters = {};
    let topK = 8;

    switch (intent) {
      case 'clarification_question':
        filters.kinds = ['lesson', 'concept', 'session_log'];
        if (this.courseManifest?.currentLessonId) {
          filters.lessonId = this.courseManifest.currentLessonId;
        }
        topK = 6;
        break;

      case 'proof_help':
        filters.kinds = ['lesson', 'concept'];
        filters.tags = ['theorem', 'proof', 'definition'];
        topK = 5;
        break;

      case 'exercise_attempt':
        filters.kinds = ['lesson', 'assignment'];
        filters.tags = ['example', 'exercise'];
        topK = 6;
        break;

      case 'meta_course_change':
        filters.kinds = ['config', 'manifest', 'syllabus'];
        topK = 4;
        break;

      case 'review_request':
        filters.kinds = ['session_log'];
        topK = 5;
        break;

      default:
        filters.kinds = ['lesson', 'concept', 'session_log'];
        topK = 8;
    }

    return { query, filters, topK };
  }

  private executeRetrieval(plan: {
    query: string;
    filters: RetrievalFilters;
    topK: number;
  }): SearchResult[] {
    const results = this.retrieval.search(plan.query, {
      filters: plan.filters,
      topK: plan.topK,
    });

    // Log retrieval
    this.db.logRetrieval({
      id: uuidv4(),
      createdAt: new Date().toISOString(),
      query: plan.query,
      filtersJson: JSON.stringify(plan.filters),
      selectedChunkIdsJson: JSON.stringify(results.map((r) => r.chunkId)),
    });

    return results;
  }

  private assembleRequest(
    userMessage: string,
    retrievedChunks: SearchResult[]
  ): GenerateRequest {
    const systemPrompt = this.buildSystemPrompt();

    // Build context from retrieved chunks
    const contextParts = retrievedChunks.map(
      (r) => `[${r.chunkKind}] ${r.heading || ''}\n${r.contentPreview}`
    );
    const contextText = contextParts.join('\n\n---\n\n');

    const messages: GenerateRequest['messages'] = [
      { role: 'system', content: systemPrompt },
    ];

    // Add retrieved context as a system message
    if (contextText) {
      messages.push({
        role: 'system',
        content: `Course Context:\n\n${contextText}`,
      });
    }

    // Add recent conversation history (last 6 messages for continuity)
    const recentMessages = this.sessionMessages.slice(-6);
    for (const msg of recentMessages) {
      messages.push({
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
      });
    }

    return {
      messages,
      responseFormat: 'text',
      temperature: 0.7,
    };
  }

  private buildSystemPrompt(): string {
    if (!this.tutorContract || !this.studentProfile || !this.courseManifest) {
      return 'You are a helpful tutor.';
    }

    const tutor = this.tutorContract;
    const student = this.studentProfile;
    const course = this.courseManifest;

    return `You are ${tutor.identity.name}, a ${tutor.identity.role}.

Your tutoring style:
- Rigor level: ${tutor.style.rigorLevel}/5
- Formality: ${tutor.style.formality}
- Lead with: ${tutor.style.leadWith.join(', ')}

Your pedagogy:
${tutor.teachingMethod.emphasizeProofs ? '- Emphasize proofs and precise reasoning\n' : ''}${tutor.teachingMethod.useAnalogies ? '- Use analogies to explain concepts\n' : ''}${tutor.teachingMethod.adaptToPace ? '- Adapt pace based on student understanding\n' : ''}
Student: ${student.displayName}
Goals: ${student.goals.join(', ')}
Preferred pace: ${student.preferences.pace}
Rigor preference: ${student.preferences.rigor}

Course: ${course.title}
Current status: ${course.status}
Subject: ${course.subject}

Use the provided course context to inform your answers. Maintain continuity with previous lessons. Be supportive and encourage questions.`;
  }

  async consolidateSession(): Promise<SessionSummary> {
    const transcript = this.sessionMessages
      .map((m) => `${m.role}: ${m.content}`)
      .join('\n\n');

    const prompt = `Based on the tutoring session transcript, produce a structured summary.

Return a JSON object with these fields:
- title: string
- date: string (ISO date)
- summary: string (brief overview)
- conceptsCovered: string[]
- misconceptions: array of { conceptId: string, text: string, severity: "low"|"medium"|"high" }
- masteryUpdates: array of { conceptId: string, delta: number, rationale: string }
- nextAgenda: string[]
- assignments: array of { title: string, body: string }

Transcript:
${transcript}`;

    const request: GenerateRequest = {
      messages: [
        { role: 'system', content: 'You are a summarization assistant. Return valid JSON only.' },
        { role: 'user', content: prompt },
      ],
      responseFormat: 'json',
      temperature: 0.3,
    };

    const result = await this.modelAdapter.generate(request);

    try {
      return JSON.parse(result.text || '{}') as SessionSummary;
    } catch {
      throw new Error('Model returned invalid JSON for session summary');
    }
  }

  getSessionMessages(): Array<{ role: string; content: string }> {
    return this.sessionMessages;
  }

  private logEvent(type: string, payload: unknown): void {
    this.db.logEvent({
      id: uuidv4(),
      eventType: type,
      createdAt: new Date().toISOString(),
      payloadJson: JSON.stringify(payload),
    });
  }
}
