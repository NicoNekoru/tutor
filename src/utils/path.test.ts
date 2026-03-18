import { describe, test, expect, beforeEach, afterEach } from 'bun:test';
import { promises as fs } from 'fs';
import path from 'path';
import os from 'os';
import {
  ensureDir,
  fileExists,
  resolveCourseRoot,
  getGlobalConfigDir,
  getGlobalPaths,
  getWorkspacePaths,
} from './path';

let tmpDir: string;

beforeEach(async () => {
  tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tutor-path-test-'));
});

afterEach(async () => {
  await fs.rm(tmpDir, { recursive: true, force: true });
});

describe('ensureDir', () => {
  test('creates a new directory', async () => {
    const dir = path.join(tmpDir, 'a', 'b', 'c');
    await ensureDir(dir);
    const stat = await fs.stat(dir);
    expect(stat.isDirectory()).toBe(true);
  });

  test('is idempotent on existing directory', async () => {
    const dir = path.join(tmpDir, 'existing');
    await fs.mkdir(dir);
    await ensureDir(dir); // should not throw
    const stat = await fs.stat(dir);
    expect(stat.isDirectory()).toBe(true);
  });
});

describe('fileExists', () => {
  test('returns true for existing file', async () => {
    const filePath = path.join(tmpDir, 'exists.txt');
    await fs.writeFile(filePath, 'hello');
    expect(await fileExists(filePath)).toBe(true);
  });

  test('returns false for missing file', async () => {
    expect(await fileExists(path.join(tmpDir, 'nope.txt'))).toBe(false);
  });

  test('returns true for existing directory', async () => {
    expect(await fileExists(tmpDir)).toBe(true);
  });
});

describe('resolveCourseRoot', () => {
  test('resolves to courses/<id> under base', () => {
    const result = resolveCourseRoot('/base', 'my-course');
    expect(result).toBe(path.resolve('/base', 'courses', 'my-course'));
  });

  test('handles relative base dir', () => {
    const result = resolveCourseRoot('.', 'c1');
    expect(result).toBe(path.resolve('.', 'courses', 'c1'));
  });
});

describe('getGlobalConfigDir', () => {
  test('returns ~/.tutor', () => {
    expect(getGlobalConfigDir()).toBe(path.join(os.homedir(), '.tutor'));
  });
});

describe('getGlobalPaths', () => {
  test('contains root and tutorConfig', () => {
    const p = getGlobalPaths();
    expect(p.root).toBe(path.join(os.homedir(), '.tutor'));
    expect(p.tutorConfig).toBe(path.join(os.homedir(), '.tutor', 'tutor.yaml'));
  });
});

describe('getWorkspacePaths', () => {
  test('returns all required paths for a course', () => {
    const p = getWorkspacePaths('/base', 'test-course');
    const root = path.resolve('/base', 'courses', 'test-course');
    expect(p.root).toBe(root);
    expect(p.manifest).toBe(path.join(root, 'manifest.yaml'));
    expect(p.tutorConfig).toBe(path.join(root, 'configs', 'tutor.yaml'));
    expect(p.studentConfig).toBe(path.join(root, 'configs', 'student.yaml'));
    expect(p.lessonsDir).toBe(path.join(root, 'lessons'));
    expect(p.conceptsDir).toBe(path.join(root, 'concepts'));
    expect(p.stateDir).toBe(path.join(root, 'state'));
    expect(p.indexDb).toBe(path.join(root, 'index', 'app.db'));
  });

  test('uses baseDir as root when courseId is omitted', () => {
    const p = getWorkspacePaths('/base');
    expect(p.root).toBe('/base');
    expect(p.manifest).toBe(path.join('/base', 'manifest.yaml'));
  });
});
