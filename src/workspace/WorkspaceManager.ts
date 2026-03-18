import { promises as fs } from 'fs';
import * as yaml from 'yaml';
import path from 'path';
import {
  v4 as uuidv4,
} from 'uuid';
import {
  CourseManifest,
  TutorConfig,
  StudentProfile,
  Syllabus,
  LessonFrontmatter,
  ConceptFrontmatter,
  MasteryState,
  DocumentKind,
} from '../schemas/types';
import { getWorkspacePaths, ensureDir, fileExists } from '../utils/path';

export class WorkspaceManager {
  private baseDir: string;
  private courseRoot: string;
  private paths: ReturnType<typeof getWorkspacePaths>;

  constructor(baseDir: string = process.cwd()) {
    this.baseDir = baseDir;
    this.courseRoot = '';
    this.paths = {} as ReturnType<typeof getWorkspacePaths>;
  }

  async createCourse(
    courseId: string,
    title: string,
    subject: string,
    tutorConfig: TutorConfig,
    studentProfile: StudentProfile
  ): Promise<string> {
    this.courseRoot = getWorkspacePaths(this.baseDir, courseId).root;

    // Create all required directories
    await Promise.all([
      ensureDir(this.courseRoot),
      ensureDir(path.join(this.courseRoot, 'configs')),
      ensureDir(path.join(this.courseRoot, 'lessons')),
      ensureDir(path.join(this.courseRoot, 'concepts')),
      ensureDir(path.join(this.courseRoot, 'assignments')),
      ensureDir(path.join(this.courseRoot, 'logs', 'sessions')),
      ensureDir(path.join(this.courseRoot, 'logs', 'summaries')),
      ensureDir(path.join(this.courseRoot, 'transcripts')),
      ensureDir(path.join(this.courseRoot, 'state')),
      ensureDir(path.join(this.courseRoot, 'index')),
    ]);

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

    // Write tutor config
    await this.writeYAML(path.join('configs', 'tutor.yaml'), tutorConfig);

    // Write student profile
    await this.writeYAML(path.join('configs', 'student.yaml'), studentProfile);

    // Write initial empty mastery state
    const masteryState: MasteryState = { concepts: {} };
    await this.writeYAML(path.join('state', 'mastery.yaml'), masteryState);

    return this.courseRoot;
  }

  async loadCourse(courseId: string): Promise<boolean> {
    const paths = getWorkspacePaths(this.baseDir, courseId);
    this.paths = paths;
    this.courseRoot = paths.root;

    // Verify essential files exist
    const requiredFiles = [
      paths.manifest,
      paths.tutorConfig,
      paths.studentConfig,
      paths.masteryState,
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
    const transcriptDir = path.join(this.courseRoot, 'transcripts');
    await ensureDir(transcriptDir);

    const dateStr = new Date().toISOString().split('T')[0];
    const transcriptFile = path.join(transcriptDir, `${dateStr}.jsonl`);

    const entryLine = JSON.stringify({
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

    await this.writeMarkdown(path.join('lessons', filename), frontmatter, content);
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
    await this.writeMarkdown(path.join('concepts', filename), frontmatter, content);
  }
}
