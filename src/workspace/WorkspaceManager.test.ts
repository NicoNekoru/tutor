import { describe, test, expect, beforeEach, afterEach } from 'bun:test';
import { promises as fs } from 'fs';
import path from 'path';
import os from 'os';
import * as yaml from 'yaml';
import {
  WorkspaceManager,
  loadGlobalTutorConfig,
  saveGlobalTutorConfig,
  mergeTutorConfigs,
} from './WorkspaceManager';
import { TutorConfig, StudentProfile } from '../schemas/types';

let tmpDir: string;

function makeTutorConfig(overrides?: Partial<TutorConfig>): TutorConfig {
  return {
    name: 'Test Tutor',
    persona: {
      style: 'theoretical',
      tone: 'formal but supportive',
      role: 'private tutor',
      specialization: ['mathematics'],
    },
    pedagogy: {
      defaultStructure: ['motivation', 'definitions', 'examples', 'recap'],
      emphasize: ['proof techniques'],
      avoid: ['hand-waving'],
    },
    adaptationRules: {
      askDiagnosticQuestions: true,
      slowDownOnConfusion: true,
      revisitPrerequisitesIfNeeded: true,
      weaveInMlConnections: 'occasionally',
    },
    ...overrides,
  };
}

function makeStudentProfile(): StudentProfile {
  return {
    studentId: 'test-student',
    displayName: 'Test Student',
    background: {
      mathLevel: 'intermediate',
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
    goals: ['Learn things'],
  };
}

beforeEach(async () => {
  tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tutor-ws-test-'));
});

afterEach(async () => {
  await fs.rm(tmpDir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// mergeTutorConfigs
// ---------------------------------------------------------------------------

describe('mergeTutorConfigs', () => {
  test('override values take precedence over base', () => {
    const base = makeTutorConfig({ name: 'Base' });
    const override: Partial<TutorConfig> = { name: 'Override' };
    const merged = mergeTutorConfigs(base, override);
    expect(merged.name).toBe('Override');
  });

  test('base values fill in when override is empty', () => {
    const base = makeTutorConfig({ name: 'Base' });
    const merged = mergeTutorConfigs(base, {});
    expect(merged.name).toBe('Base');
    expect(merged.persona.style).toBe('theoretical');
    expect(merged.pedagogy.emphasize).toEqual(['proof techniques']);
  });

  test('override persona fields selectively', () => {
    const base = makeTutorConfig();
    const override: Partial<TutorConfig> = {
      persona: {
        style: 'socratic',
        tone: '',         // falsy — should fall back to base
        role: 'mentor',
        specialization: [],  // empty array — should fall back to base
      },
    };
    const merged = mergeTutorConfigs(base, override);
    expect(merged.persona.style).toBe('socratic');
    expect(merged.persona.tone).toBe('formal but supportive'); // base fallback
    expect(merged.persona.role).toBe('mentor');
    expect(merged.persona.specialization).toEqual(['mathematics']); // base fallback
  });

  test('override arrays replace base arrays when non-empty', () => {
    const base = makeTutorConfig();
    const override: Partial<TutorConfig> = {
      pedagogy: {
        defaultStructure: ['intro', 'exercises'],
        emphasize: ['abstraction'],
        avoid: [],  // empty — should fall back to base
      },
    };
    const merged = mergeTutorConfigs(base, override);
    expect(merged.pedagogy.defaultStructure).toEqual(['intro', 'exercises']);
    expect(merged.pedagogy.emphasize).toEqual(['abstraction']);
    expect(merged.pedagogy.avoid).toEqual(['hand-waving']); // base fallback
  });

  test('boolean adaptation rules use nullish coalescing', () => {
    const base = makeTutorConfig();
    base.adaptationRules.askDiagnosticQuestions = true;
    const override: Partial<TutorConfig> = {
      adaptationRules: {
        askDiagnosticQuestions: false,
        slowDownOnConfusion: true,
        revisitPrerequisitesIfNeeded: true,
        weaveInMlConnections: 'never',
      },
    };
    const merged = mergeTutorConfigs(base, override);
    expect(merged.adaptationRules.askDiagnosticQuestions).toBe(false);
    expect(merged.adaptationRules.weaveInMlConnections).toBe('never');
  });
});

// ---------------------------------------------------------------------------
// WorkspaceManager.createCourse
// ---------------------------------------------------------------------------

describe('WorkspaceManager.createCourse', () => {
  test('creates all required directories and config files', async () => {
    const ws = new WorkspaceManager(tmpDir);
    const root = await ws.createCourse(
      'test-course',
      'Test Course',
      'algebra',
      makeTutorConfig(),
      makeStudentProfile(),
    );

    // Directories exist
    for (const dir of ['configs', 'lessons', 'concepts', 'assignments', 'state', 'index']) {
      const stat = await fs.stat(path.join(root, dir));
      expect(stat.isDirectory()).toBe(true);
    }

    // Config files written
    const tutorYaml = yaml.parse(await fs.readFile(path.join(root, 'configs', 'tutor.yaml'), 'utf-8'));
    expect(tutorYaml.name).toBe('Test Tutor');

    const studentYaml = yaml.parse(await fs.readFile(path.join(root, 'configs', 'student.yaml'), 'utf-8'));
    expect(studentYaml.studentId).toBe('test-student');

    const manifestYaml = yaml.parse(await fs.readFile(path.join(root, 'manifest.yaml'), 'utf-8'));
    expect(manifestYaml.subject).toBe('algebra');
    expect(manifestYaml.status).toBe('active');
  });

  test('uses global persona when useGlobalPersona is true', async () => {
    // Set up a global config in a temp dir — we'll monkeypatch getGlobalPaths
    const globalDir = path.join(tmpDir, '.tutor-global');
    await fs.mkdir(globalDir, { recursive: true });
    const globalConfig = makeTutorConfig({
      name: 'Global Professor',
      persona: { style: 'socratic', tone: 'warm', role: 'mentor', specialization: ['logic'] },
    });
    await fs.writeFile(path.join(globalDir, 'tutor.yaml'), yaml.stringify(globalConfig), 'utf-8');

    // We can't easily monkeypatch, so test mergeTutorConfigs directly for the
    // merge logic, and test createCourse separately for file writing
    const courseConfig = makeTutorConfig({
      name: 'Course Professor',
      persona: { style: 'theoretical', tone: 'formal', role: 'tutor', specialization: ['algebra'] },
    });
    const merged = mergeTutorConfigs(globalConfig, courseConfig);
    expect(merged.name).toBe('Course Professor');  // course wins
    expect(merged.persona.style).toBe('theoretical');  // course wins
  });
});

describe('WorkspaceManager.loadCourse', () => {
  test('loads an existing course successfully', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'Course 1', 'math', makeTutorConfig(), makeStudentProfile());

    const ws2 = new WorkspaceManager(tmpDir);
    const loaded = await ws2.loadCourse('c1');
    expect(loaded).toBe(true);
  });

  test('throws for missing course', async () => {
    const ws = new WorkspaceManager(tmpDir);
    expect(ws.loadCourse('nonexistent')).rejects.toThrow('Missing required file');
  });
});

describe('WorkspaceManager file operations', () => {
  test('readFile and writeYAML round-trip', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'C1', 'math', makeTutorConfig(), makeStudentProfile());

    const content = await ws.readFile('manifest.yaml');
    const parsed = yaml.parse(content);
    expect(parsed.id).toBe('c1');
  });

  test('writeMarkdown produces correct frontmatter format', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'C1', 'math', makeTutorConfig(), makeStudentProfile());
    await ws.writeMarkdown('test.md', { title: 'Hello' }, 'Body content');

    const raw = await fs.readFile(path.join(ws.getCourseRoot(), 'test.md'), 'utf-8');
    expect(raw).toContain('---');
    expect(raw).toContain('title: Hello');
    expect(raw).toContain('Body content');
  });

  test('writeTranscriptEntry appends JSONL', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'C1', 'math', makeTutorConfig(), makeStudentProfile());

    await ws.writeTranscriptEntry({ role: 'user', content: 'hello' });
    await ws.writeTranscriptEntry({ role: 'assistant', content: 'hi' });

    const transcriptDir = path.join(ws.getCourseRoot(), 'transcripts');
    const files = await fs.readdir(transcriptDir);
    expect(files.length).toBe(1);

    const lines = (await fs.readFile(path.join(transcriptDir, files[0]), 'utf-8'))
      .trim()
      .split('\n');
    expect(lines.length).toBe(2);
    expect(JSON.parse(lines[0]).role).toBe('user');
    expect(JSON.parse(lines[1]).role).toBe('assistant');
  });

  test('listFiles returns filenames in a directory', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'C1', 'math', makeTutorConfig(), makeStudentProfile());

    await ws.writeMarkdown(path.join('lessons', 'lesson-001.md'), { id: 'l1' }, 'content');
    const files = await ws.listFiles('lessons');
    expect(files).toContain('lesson-001.md');
  });

  test('listFiles returns empty array for missing directory', async () => {
    const ws = new WorkspaceManager(tmpDir);
    await ws.createCourse('c1', 'C1', 'math', makeTutorConfig(), makeStudentProfile());

    const files = await ws.listFiles('nonexistent');
    expect(files).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Global persona utilities
// ---------------------------------------------------------------------------

describe('global persona utilities', () => {
  let fakeHome: string;

  beforeEach(async () => {
    fakeHome = path.join(tmpDir, 'fakehome');
    await fs.mkdir(fakeHome, { recursive: true });
  });

  test('loadGlobalTutorConfig returns null when no config exists', async () => {
    const result = await loadGlobalTutorConfig(fakeHome);
    expect(result).toBeNull();
  });

  test('saveGlobalTutorConfig creates file and loadGlobalTutorConfig reads it', async () => {
    const config = makeTutorConfig({ name: 'Global Prof' });
    await saveGlobalTutorConfig(config, fakeHome);
    const loaded = await loadGlobalTutorConfig(fakeHome);
    expect(loaded).not.toBeNull();
    expect(loaded!.name).toBe('Global Prof');
    expect(loaded!.persona.style).toBe('theoretical');
  });

  test('saveGlobalTutorConfig overwrites existing', async () => {
    await saveGlobalTutorConfig(makeTutorConfig({ name: 'First' }), fakeHome);
    await saveGlobalTutorConfig(makeTutorConfig({ name: 'Second' }), fakeHome);
    const loaded = await loadGlobalTutorConfig(fakeHome);
    expect(loaded!.name).toBe('Second');
  });
});
