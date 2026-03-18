import path from 'path';
import { promises as fs } from 'fs';
import parse from 'front-matter';
import {
  DocumentKind,
  ChunkKind,
  LessonFrontmatter,
  ConceptFrontmatter,
  DocumentEntry,
  ChunkEntry,
} from '../schemas/types';

// Estimate token count (approximate: 4 chars per token)
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

// Simple checksum function
function checksum(content: string): string {
  let hash = 0;
  for (let i = 0; i < content.length; i++) {
    hash = ((hash << 5) - hash) + content.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString(36);
}

// Split markdown content into semantic chunks based on headings
function splitByHeadings(markdown: string): Array<{ heading?: string; content: string }> {
  const lines = markdown.split('\n');
  const chunks: Array<{ heading?: string; content: string }> = [];
  let currentChunk: { heading?: string; content: string } = { content: '' };

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      if (currentChunk.content.trim()) {
        chunks.push(currentChunk);
      }
      currentChunk = {
        heading: headingMatch[2],
        content: line + '\n',
      };
    } else {
      currentChunk.content += line + '\n';
    }
  }

  if (currentChunk.content.trim()) {
    chunks.push(currentChunk);
  }

  return chunks;
}

// Determine chunk kind based on heading content
function inferChunkKind(
  heading: string | undefined,
  _content: string,
  documentKind: DocumentKind
): ChunkKind {
  if (!heading) {
    return 'overview';
  }

  const h = heading.toLowerCase();

  if (h.includes('objective') || h.includes('goal')) return 'objective';
  if (h.includes('motivation') || h.includes('why')) return 'motivation';
  if (h.includes('definition') || h.includes('define')) return 'definition';
  if (h.includes('theorem') || h.includes('lemma') || h.includes('proposition')) return 'theorem';
  if (h.includes('proof')) return 'proof';
  if (h.includes('example') || h.includes('illustration')) return 'example';
  if (h.includes('exercise') || h.includes('problem') || h.includes('question')) return 'exercise';
  if (h.includes('misconception') || h.includes('common mistake') || h.includes('confusion')) return 'misconception';
  if (h.includes('summary') || h.includes('recap') || h.includes('conclusion')) return 'summary';
  if (h.includes('reflection') || h.includes('thoughts')) return 'reflection';
  if (h.includes('faq') || h.includes('?')) return 'faq';

  if (documentKind === 'concept') return 'definition';
  if (documentKind === 'lesson') return 'overview';

  return 'overview';
}

// Extract document metadata from frontmatter
export function extractDocumentEntry(
  filePath: string,
  relativePath: string,
  content: string,
  kind: DocumentKind
): DocumentEntry | null {
  try {
    let attributes: Record<string, any> = {};

    // Only parse frontmatter for markdown files
    if (filePath.endsWith('.md')) {
      const parsed = parse(content);
      attributes = parsed.attributes as Record<string, any>;
    }

    const filename = path.basename(filePath);
    const idFromFile = path.basename(filename, path.extname(filename));

    const doc: DocumentEntry = {
      id: '',
      path: relativePath,
      kind,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      checksum: checksum(content),
    };

    switch (kind) {
      case 'lesson': {
        const lesson = attributes as Partial<LessonFrontmatter>;
        doc.id = lesson.id || idFromFile;
        doc.title = lesson.title;
        doc.lessonId = lesson.id;
        doc.unit = lesson.unit;
        break;
      }
      case 'concept': {
        const concept = attributes as Partial<ConceptFrontmatter>;
        doc.id = concept.id || idFromFile;
        doc.title = concept.title;
        doc.conceptId = concept.id;
        break;
      }
      case 'syllabus':
        doc.id = 'syllabus';
        doc.title = 'Syllabus';
        break;
      case 'manifest':
        doc.id = 'manifest';
        doc.title = 'Course Manifest';
        break;
      case 'state':
        doc.id = idFromFile;
        doc.title = idFromFile;
        break;
      case 'assignment':
      case 'session_log':
        doc.id = idFromFile;
        doc.title = (attributes as { title?: string }).title || idFromFile;
        break;
      case 'config':
        doc.id = idFromFile;
        doc.title = idFromFile;
        break;
    }

    return doc;
  } catch (error) {
    console.error(`Failed to parse ${filePath}:`, error);
    return null;
  }
}

// Given a document entry and content, produce chunks
export function extractChunks(
  doc: DocumentEntry,
  content: string
): ChunkEntry[] {
  const chunks: ChunkEntry[] = [];

  if (!doc.path.endsWith('.md')) {
    chunks.push({
      id: `${doc.id}:full`,
      documentId: doc.id,
      chunkKind: 'overview',
      ordinal: 0,
      content,
      tokenEstimate: estimateTokens(content),
    });
    return chunks;
  }

  const { attributes, body } = parse(content);

  // First chunk: frontmatter/metadata summary
  const fmSummary = `Frontmatter: ${JSON.stringify(attributes, null, 2)}`;
  chunks.push({
    id: `${doc.id}:frontmatter`,
    documentId: doc.id,
    chunkKind: 'summary',
    ordinal: 0,
    heading: 'Metadata',
    content: fmSummary,
    tokenEstimate: estimateTokens(fmSummary),
  });

  // Split the markdown body by headings
  const markdownChunks = splitByHeadings(body);

  for (let i = 0; i < markdownChunks.length; i++) {
    const { heading, content: chunkContent } = markdownChunks[i];
    const chunkKind = inferChunkKind(heading, chunkContent, doc.kind);

    const chunkId = heading
      ? `${doc.id}:${heading.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')}-${i}`
      : `${doc.id}:chunk-${i}`;

    chunks.push({
      id: chunkId,
      documentId: doc.id,
      chunkKind,
      ordinal: i + 1,
      heading,
      content: chunkContent,
      tokenEstimate: estimateTokens(chunkContent),
    });
  }

  return chunks;
}

// File discovery — walk directory and collect .md and .yaml files
export async function discoverFiles(workspaceRoot: string): Promise<string[]> {
  const allFiles: string[] = [];
  const VALID_EXTENSIONS = new Set(['.md', '.yaml', '.yml']);

  async function walk(dir: string): Promise<void> {
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);

      // Skip index directory and hidden dirs
      if (entry.isDirectory()) {
        if (entry.name === 'index' || entry.name === 'transcripts' || entry.name.startsWith('.')) {
          continue;
        }
        await walk(fullPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name);
        if (VALID_EXTENSIONS.has(ext)) {
          allFiles.push(fullPath);
        }
      }
    }
  }

  await walk(workspaceRoot);
  return allFiles;
}
