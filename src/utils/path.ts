import { promises as fs } from 'fs';
import path from 'path';
import os from 'os';

export async function ensureDir(dirPath: string): Promise<void> {
  await fs.mkdir(dirPath, { recursive: true });
}

export async function fileExists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

export function resolveCourseRoot(baseDir: string, courseId: string): string {
  return path.resolve(baseDir, 'courses', courseId);
}

export function getGlobalConfigDir(): string {
  return path.join(os.homedir(), '.tutor');
}

export function getGlobalPaths() {
  const globalDir = getGlobalConfigDir();
  return {
    root: globalDir,
    tutorConfig: path.join(globalDir, 'tutor.yaml'),
  };
}

export function getWorkspacePaths(baseDir: string, courseId?: string) {
  const courseRoot = courseId
    ? resolveCourseRoot(baseDir, courseId)
    : baseDir;

  return {
    root: courseRoot,
    manifest: path.join(courseRoot, 'manifest.yaml'),
    syllabus: path.join(courseRoot, 'syllabus.md'),
    configs: path.join(courseRoot, 'configs'),
    tutorConfig: path.join(courseRoot, 'configs', 'tutor.yaml'),
    studentConfig: path.join(courseRoot, 'configs', 'student.yaml'),
    retrievalConfig: path.join(courseRoot, 'configs', 'retrieval.yaml'),
    modelConfig: path.join(courseRoot, 'configs', 'model.yaml'),
    lessonsDir: path.join(courseRoot, 'lessons'),
    conceptsDir: path.join(courseRoot, 'concepts'),
    assignmentsDir: path.join(courseRoot, 'assignments'),
    logsDir: path.join(courseRoot, 'logs'),
    sessionLogsDir: path.join(courseRoot, 'logs', 'sessions'),
    summariesDir: path.join(courseRoot, 'logs', 'summaries'),
    transcriptsDir: path.join(courseRoot, 'transcripts'),
    stateDir: path.join(courseRoot, 'state'),
    masteryState: path.join(courseRoot, 'state', 'mastery.yaml'),
    currentSession: path.join(courseRoot, 'state', 'current_session.yaml'),
    agenda: path.join(courseRoot, 'state', 'agenda.yaml'),
    indexDir: path.join(courseRoot, 'index'),
    indexDb: path.join(courseRoot, 'index', 'app.db'),
  };
}
