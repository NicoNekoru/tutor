#!/usr/bin/env bun

import { Command } from 'commander';
import path from 'path';
import { promises as fs } from 'fs';
import { v4 as uuidv4 } from 'uuid';

import { WorkspaceManager } from './workspace/WorkspaceManager';
import { SQLiteDatabase } from './indexer/Database';
import { Indexer } from './indexer/Indexer';
import { RetrievalEngine } from './retrieval/RetrievalEngine';
import { CLIModelAdapter, ModelBackendConfig } from './adapter/ModelAdapter';
import { Orchestrator } from './orchestrator/Orchestrator';
import { TutorTUI } from './tui/TUI';
import {
  TutorConfig,
  StudentProfile,
  CourseManifest,
  Syllabus,
} from './schemas/types';

const program = new Command();
const BASE_DIR = process.cwd();

program
  .name('tutor')
  .description('RLM-based tutoring application with persistent pedagogical memory')
  .version('0.1.0');

program
  .command('init')
  .description('Initialize a new tutoring course')
  .option('--course-id <id>', 'Course identifier', 'my-course')
  .option('--subject <subject>', 'Subject area', 'mathematics')
  .option('--tutor-name <name>', 'Tutor name', 'Professor')
  .option('--persona <style>', 'Tutor persona', 'theoretical')
  .action(async (options) => {
    console.log('Initializing new course...');

    const courseId = options.courseId;
    const subject = options.subject;

    // Create workspace
    const ws = new WorkspaceManager(BASE_DIR);
    await ws.createCourse(
      courseId,
      `${subject.charAt(0).toUpperCase() + subject.slice(1)} Private Tutoring`,
      subject,
      {
        name: `${options.tutorName} ${options.persona}`,
        persona: {
          style: options.persona,
          tone: 'formal but supportive',
          role: 'private tutor',
          specialization: [subject],
        },
        pedagogy: {
          defaultStructure: [
            'motivation',
            'precise definitions',
            'theorem or principle',
            'proof sketch',
            'examples',
            'student exercise',
            'recap',
          ],
          emphasize: ['proof techniques', 'abstraction', 'invariants', 'exact reasoning'],
          avoid: ['superficial intuition without formal grounding'],
        },
        adaptationRules: {
          askDiagnosticQuestions: true,
          slowDownOnConfusion: true,
          revisitPrerequisitesIfNeeded: true,
          weaveInMlConnections: 'occasionally',
        },
      },
      {
        studentId: 'default',
        displayName: 'Student',
        background: {
          mathLevel: 'unknown',
          priorCourses: [],
          strengths: [],
          weakAreas: [],
        },
        preferences: {
          pace: 'moderate',
          rigor: 'high',
          examplesBeforeProofs: false,
          exercisesPerLesson: 3,
        },
        goals: [`Learn ${subject} rigorously`, 'Improve proof-writing', 'Understand applications'],
      }
    );

    // Create SQLite index
    const db = new SQLiteDatabase();
    await db.initialize();

    // Index the workspace
    const indexer = new Indexer(db, ws);
    await indexer.indexWorkspace(ws.getCourseRoot());

    console.log('Course initialized at:', ws.getCourseRoot());
    console.log('Now run: tutor start');
  });

program
  .command('start')
  .description('Start the TUI for an existing course')
  .option('--course-id <id>', 'Course identifier', 'my-course')
  .action(async (options) => {
    const courseId = options.courseId;
    const ws = new WorkspaceManager(BASE_DIR);

    try {
      await ws.loadCourse(courseId);
      console.log('Loaded course:', courseId);
    } catch (error) {
      console.error(`Failed to load course "${courseId}":`, error);
      process.exit(1);
    }

    // Initialize database
    const db = new SQLiteDatabase();
    await db.initialize();

    // Initialize retrieval
    const retrieval = new RetrievalEngine(db);

    // Initialize model adapter (placeholder config)
    const modelConfig: ModelBackendConfig = {
      command: 'opencode', // or another CLI
      args: ['--json'],
    };
    const modelAdapter = CLIModelAdapter(modelConfig);

    // Initialize orchestrator
    const orchestrator = new Orchestrator(modelAdapter, retrieval, ws, db);
    await orchestrator.initializeSession();

    // Start TUI
    const tui = new TutorTUI(orchestrator, ws);
    tui.start();
  });

program
  .command('reindex')
  .description('Rebuild the search index')
  .option('--course-id <id>', 'Course identifier', 'my-course')
  .action(async (options) => {
    const courseId = options.courseId;
    const ws = new WorkspaceManager(BASE_DIR);

    try {
      await ws.loadCourse(courseId);
    } catch (error) {
      console.error(`Failed to load course "${courseId}":`, error);
      process.exit(1);
    }

    const dbPath = ws.getPaths().indexDb;
    const db = new SQLiteDatabase(dbPath);
    const indexer = new Indexer(db, ws);

    console.log('Rebuilding index...');
    await indexer.reindex(ws.getCourseRoot());
    console.log('Reindex complete');
  });

program.parse();
