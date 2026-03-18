import { promises as fs } from 'fs';
import * as yaml from 'yaml';
import path from 'path';
import {
  CourseManifest,
  TutorConfig,
  StudentProfile,
  MasteryState,
  LessonFrontmatter,
  ConceptFrontmatter,
} from '../schemas/types';
import { getWorkspacePaths, getGlobalPaths, ensureDir, fileExists } from '../utils/path';

export class WorkspaceManager {
  private baseDir: string;
  private courseRoot: string = '';
  private paths!: ReturnType<typeof getWorkspacePaths>;

  constructor(baseDir: string = process.cwd()) {
    this.baseDir = baseDir;
  }

  async createCourse(
    courseId: string,
    title: string,
    subject: string,
    tutorConfig: TutorConfig,
    studentProfile: StudentProfile,
    options?: { useGlobalPersona?: boolean }
  ): Promise<string> {
    this.paths = getWorkspacePaths(this.baseDir, courseId);
    this.courseRoot = this.paths.root;

    // Create all required directories
    await Promise.all([
      ensureDir(this.courseRoot),
      ensureDir(this.paths.configs),
      ensureDir(this.paths.lessonsDir),
      ensureDir(this.paths.conceptsDir),
      ensureDir(this.paths.assignmentsDir),
      ensureDir(this.paths.sessionLogsDir),
      ensureDir(this.paths.summariesDir),
      ensureDir(this.paths.transcriptsDir),
      ensureDir(this.paths.stateDir),
      ensureDir(this.paths.indexDir),
    ]);

    // If --from-global, merge global persona as base with course-specific overrides on top
    let finalTutorConfig = tutorConfig;
    if (options?.useGlobalPersona) {
      const globalConfig = await loadGlobalTutorConfig();
      if (globalConfig) {
        finalTutorConfig = mergeTutorConfigs(globalConfig, tutorConfig);
      }
    }

    // Write manifest
    const manifest: CourseManifest = {
      id: courseId,
      title,
      subject,
      status: 'active',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      syllabusVersion: 1,
      courseGoals: [],
      policies: {
        adaptationMode: 'high',
        retrievalMode: 'hybrid',
        sessionConsolidation: 'required',
      },
    };
    await this.writeYAML('manifest.yaml', manifest);

    // Write tutor config (course-local, the primary layer)
    await this.writeYAML(path.join('configs', 'tutor.yaml'), finalTutorConfig);

    // Write student profile
    await this.writeYAML(path.join('configs', 'student.yaml'), studentProfile);

    // Write initial empty mastery state
    const masteryState: MasteryState = { concepts: {} };
    await this.writeYAML(path.join('state', 'mastery.yaml'), masteryState);

    return this.courseRoot;
  }

  async loadCourse(courseId: string): Promise<boolean> {
    this.paths = getWorkspacePaths(this.baseDir, courseId);
    this.courseRoot = this.paths.root;

    // Verify essential files exist
    const requiredFiles = [
      this.paths.manifest,
      this.paths.tutorConfig,
      this.paths.studentConfig,
      this.paths.masteryState,
    ];

    for (const file of requiredFiles) {
      if (!(await fileExists(file))) {
        throw new Error(`Missing required file: ${file}`);
      }
    }

    return true;
  }

  async writeMarkdown(
    relativePath: string,
    frontmatter: Record<string, unknown>,
    content: string
  ): Promise<void> {
    const fullPath = path.join(this.courseRoot, relativePath);
    const frontmatterYAML = yaml.stringify(frontmatter);
    const markdown = `---\n${frontmatterYAML}---\n\n${content}`;
    await fs.writeFile(fullPath, markdown, 'utf-8');
  }

  async writeYAML<T>(relativePath: string, data: T): Promise<void> {
    const fullPath = path.join(this.courseRoot, relativePath);
    const yamlStr = yaml.stringify(data);
    await fs.writeFile(fullPath, yamlStr, 'utf-8');
  }

  async appendToFile(relativePath: string, content: string): Promise<void> {
    const fullPath = path.join(this.courseRoot, relativePath);
    await fs.appendFile(fullPath, content, 'utf-8');
  }

  async readFile(relativePath: string): Promise<string> {
    const fullPath = path.join(this.courseRoot, relativePath);
    return fs.readFile(fullPath, 'utf-8');
  }

  async listFiles(dirRelativePath: string): Promise<string[]> {
    const dirPath = path.join(this.courseRoot, dirRelativePath);
    try {
      const entries = await fs.readdir(dirPath, { withFileTypes: true });
      return entries.filter((e) => e.isFile()).map((e) => e.name);
    } catch {
      return [];
    }
  }

  async writeTranscriptEntry(entry: { role: string; content: string }): Promise<void> {
    await ensureDir(this.paths.transcriptsDir);

    const dateStr = new Date().toISOString().split('T')[0];
    const transcriptFile = path.join(this.paths.transcriptsDir, `${dateStr}.jsonl`);

    const entryLine =
      JSON.stringify({
        ...entry,
        timestamp: new Date().toISOString(),
      }) + '\n';

    await fs.appendFile(transcriptFile, entryLine, 'utf-8');
  }

  getCourseRoot(): string {
    return this.courseRoot;
  }

  getPaths(): ReturnType<typeof getWorkspacePaths> {
    return this.paths;
  }

  async createLesson(
    lessonNumber: number,
    title: string,
    unit: string,
    concepts: string[],
    content: string
  ): Promise<string> {
    const lessonId = `lesson-${String(lessonNumber).padStart(3, '0')}`;
    const filename = `${lessonId}-${title.toLowerCase().replace(/\s+/g, '-')}.md`;

    const frontmatter: LessonFrontmatter = {
      id: lessonId,
      title,
      lessonNumber,
      status: 'draft',
      unit,
      concepts,
      prerequisites: [],
      objectives: [],
    };

    await this.writeMarkdown(path.join('lessons', filename), frontmatter as unknown as Record<string, unknown>, content);
    return filename;
  }

  async createConcept(
    conceptId: string,
    title: string,
    content: string,
    related: string[] = [],
    prerequisites: string[] = []
  ): Promise<void> {
    const frontmatter: ConceptFrontmatter = {
      id: conceptId,
      title,
      aliases: [],
      tags: [],
      prerequisites,
      related,
    };

    const filename = `${conceptId}.md`;
    await this.writeMarkdown(path.join('concepts', filename), frontmatter as unknown as Record<string, unknown>, content);
  }
}

// ---------------------------------------------------------------------------
// Global persona utilities
// ---------------------------------------------------------------------------

/**
 * Load the global tutor persona from ~/.tutor/tutor.yaml.
 * Returns null if no global persona is configured.
 */
export async function loadGlobalTutorConfig(): Promise<TutorConfig | null> {
  const globalPaths = getGlobalPaths();
  if (!(await fileExists(globalPaths.tutorConfig))) {
    return null;
  }
  const content = await fs.readFile(globalPaths.tutorConfig, 'utf-8');
  return yaml.parse(content) as TutorConfig;
}

/**
 * Save a tutor persona as the global default in ~/.tutor/tutor.yaml.
 */
export async function saveGlobalTutorConfig(config: TutorConfig): Promise<void> {
  const globalPaths = getGlobalPaths();
  await ensureDir(globalPaths.root);
  await fs.writeFile(globalPaths.tutorConfig, yaml.stringify(config), 'utf-8');
}

/**
 * Merge two TutorConfig objects. `override` values take precedence;
 * `base` fills in anything the override doesn't specify. Arrays are
 * replaced (not concatenated) when the override provides them.
 */
export function mergeTutorConfigs(base: TutorConfig, override: Partial<TutorConfig>): TutorConfig {
  return {
    name: override.name || base.name,
    persona: {
      style: override.persona?.style || base.persona.style,
      tone: override.persona?.tone || base.persona.tone,
      role: override.persona?.role || base.persona.role,
      specialization: override.persona?.specialization?.length
        ? override.persona.specialization
        : base.persona.specialization,
    },
    pedagogy: {
      defaultStructure: override.pedagogy?.defaultStructure?.length
        ? override.pedagogy.defaultStructure
        : base.pedagogy.defaultStructure,
      emphasize: override.pedagogy?.emphasize?.length
        ? override.pedagogy.emphasize
        : base.pedagogy.emphasize,
      avoid: override.pedagogy?.avoid?.length
        ? override.pedagogy.avoid
        : base.pedagogy.avoid,
    },
    adaptationRules: {
      askDiagnosticQuestions: override.adaptationRules?.askDiagnosticQuestions ?? base.adaptationRules.askDiagnosticQuestions,
      slowDownOnConfusion: override.adaptationRules?.slowDownOnConfusion ?? base.adaptationRules.slowDownOnConfusion,
      revisitPrerequisitesIfNeeded: override.adaptationRules?.revisitPrerequisitesIfNeeded ?? base.adaptationRules.revisitPrerequisitesIfNeeded,
      weaveInMlConnections: override.adaptationRules?.weaveInMlConnections || base.adaptationRules.weaveInMlConnections,
    },
  };
}
