#!/usr/bin/env bun

import { Command } from 'commander';
import { v4 as uuidv4 } from 'uuid';
import * as yaml from 'yaml';

import { WorkspaceManager, loadGlobalTutorConfig, saveGlobalTutorConfig } from './workspace/WorkspaceManager';
import { SQLiteDatabase } from './indexer/Database';
import { Indexer } from './indexer/Indexer';
import { RetrievalEngine } from './retrieval/RetrievalEngine';
import { createModelAdapter, ModelBackendConfig } from './adapter/ModelAdapter';
import { Orchestrator } from './orchestrator/Orchestrator';
import { TutorTUI } from './tui/TUI';
import { TutorConfig } from './schemas/types';
import { getGlobalPaths } from './utils/path';

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
  .option('--persona <style>', 'Tutor persona style', 'theoretical')
  .option('--from-global', 'Seed course persona from global ~/.tutor/tutor.yaml defaults')
  .action(async (options) => {
    console.log('Initializing new course...');

    const courseId = options.courseId;
    const subject = options.subject;

    const courseTutorConfig: TutorConfig = {
      name: `${options.tutorName} of ${subject.charAt(0).toUpperCase() + subject.slice(1)}`,
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
    };

    // Create workspace
    const ws = new WorkspaceManager(BASE_DIR);
    const courseRoot = await ws.createCourse(
      courseId,
      `${subject.charAt(0).toUpperCase() + subject.slice(1)} Private Tutoring`,
      subject,
      courseTutorConfig,
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
      },
      { useGlobalPersona: !!options.fromGlobal }
    );

    if (options.fromGlobal) {
      const globalConfig = await loadGlobalTutorConfig();
      if (globalConfig) {
        console.log('Merged global persona defaults from ~/.tutor/tutor.yaml');
      } else {
        console.log('Note: --from-global specified but no global persona found at ~/.tutor/tutor.yaml');
      }
    }

    // Create and persist SQLite index
    const dbPath = ws.getPaths().indexDb;
    const db = new SQLiteDatabase(dbPath);
    await db.initialize();

    // Index the workspace
    const indexer = new Indexer(db, ws);
    await indexer.indexWorkspace(courseRoot);

    // Save database
    await db.save();

    // Log event
    db.logEvent({
      id: uuidv4(),
      eventType: 'course_initialized',
      createdAt: new Date().toISOString(),
      payloadJson: JSON.stringify({ courseId, subject, usedGlobalPersona: !!options.fromGlobal }),
    });
    await db.save();

    console.log(`Course initialized at: ${courseRoot}`);
    console.log('Now run: bun src/index.ts start --course-id ' + courseId);
  });

// ---------------------------------------------------------------------------
// persona command — manage global tutor persona
// ---------------------------------------------------------------------------

const personaCmd = program
  .command('persona')
  .description('Manage global tutor persona (~/.tutor/tutor.yaml)');

personaCmd
  .command('show')
  .description('Display the current global tutor persona')
  .action(async () => {
    const config = await loadGlobalTutorConfig();
    if (!config) {
      console.log('No global persona configured.');
      console.log(`Set one with: tutor persona set --name "Professor" --style "theoretical" --tone "formal"`);
      console.log(`Or create ~/.tutor/tutor.yaml manually.`);
      return;
    }
    console.log(yaml.stringify(config));
  });

personaCmd
  .command('set')
  .description('Set or update the global tutor persona')
  .option('--name <name>', 'Tutor name')
  .option('--style <style>', 'Persona style (e.g. theoretical, socratic, practical)')
  .option('--tone <tone>', 'Persona tone (e.g. formal, semi-formal, casual)')
  .option('--role <role>', 'Persona role (e.g. private tutor, lecturer)')
  .option('--specialization <items>', 'Comma-separated specializations')
  .option('--emphasize <items>', 'Comma-separated pedagogy emphases')
  .option('--avoid <items>', 'Comma-separated pedagogy avoidances')
  .action(async (options) => {
    // Load existing or start fresh
    const existing = await loadGlobalTutorConfig();

    const config: TutorConfig = {
      name: options.name || existing?.name || 'Tutor',
      persona: {
        style: options.style || existing?.persona?.style || 'theoretical',
        tone: options.tone || existing?.persona?.tone || 'formal but supportive',
        role: options.role || existing?.persona?.role || 'private tutor',
        specialization: options.specialization
          ? options.specialization.split(',').map((s: string) => s.trim())
          : existing?.persona?.specialization || [],
      },
      pedagogy: {
        defaultStructure: existing?.pedagogy?.defaultStructure || [
          'motivation',
          'definitions',
          'theorem',
          'proof sketch',
          'examples',
          'exercises',
          'recap',
        ],
        emphasize: options.emphasize
          ? options.emphasize.split(',').map((s: string) => s.trim())
          : existing?.pedagogy?.emphasize || [],
        avoid: options.avoid
          ? options.avoid.split(',').map((s: string) => s.trim())
          : existing?.pedagogy?.avoid || [],
      },
      adaptationRules: existing?.adaptationRules || {
        askDiagnosticQuestions: true,
        slowDownOnConfusion: true,
        revisitPrerequisitesIfNeeded: true,
        weaveInMlConnections: 'occasionally',
      },
    };

    await saveGlobalTutorConfig(config);
    console.log(`Global persona saved to ${getGlobalPaths().tutorConfig}`);
    console.log(yaml.stringify(config));
  });

personaCmd
  .command('path')
  .description('Print the global persona config file path')
  .action(() => {
    console.log(getGlobalPaths().tutorConfig);
  });

// ---------------------------------------------------------------------------
// start command
// ---------------------------------------------------------------------------

program
  .command('start')
  .description('Start the TUI for an existing course')
  .option('--course-id <id>', 'Course identifier', 'my-course')
  .option('--model-command <cmd>', 'Model backend CLI command')
  .option('--model-args <args>', 'Model backend CLI args (comma-separated)')
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
    const dbPath = ws.getPaths().indexDb;
    const db = new SQLiteDatabase(dbPath);
    await db.initialize();

    // Initialize retrieval
    const retrieval = new RetrievalEngine(db);

    // Initialize model adapter
    let modelConfig: ModelBackendConfig | undefined;
    if (options.modelCommand) {
      modelConfig = {
        command: options.modelCommand,
        args: options.modelArgs ? options.modelArgs.split(',') : [],
      };
    }
    const modelAdapter = createModelAdapter(modelConfig);

    // Initialize orchestrator
    const orchestrator = new Orchestrator(modelAdapter, retrieval, ws, db);
    await orchestrator.initializeSession();

    // Start TUI
    const tui = new TutorTUI(orchestrator, ws);
    tui.start();
  });

// ---------------------------------------------------------------------------
// reindex command
// ---------------------------------------------------------------------------

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
    await db.initialize();

    const indexer = new Indexer(db, ws);

    console.log('Rebuilding index...');
    await indexer.reindex(ws.getCourseRoot());
    await db.save();
    console.log('Reindex complete');
  });

program.parse();
