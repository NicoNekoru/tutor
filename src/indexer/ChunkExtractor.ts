import path from 'path';
import { promises as fs } from 'fs';
import { parse } from 'front-matter';
import { marked } from 'marked';
import { v4 as uuidv4 } from 'uuid';
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
    hash |= 0; // Convert to 32-bit integer
  }
  return hash.toString(36);
}

// Split markdown content into semantic chunks based on headings
function splitByHeadings(markdown: string): Array<{ heading?: string; content: string }> {
  const lines = markdown.split('\n');
  const chunks: Array<{ heading?: string; content: string }> = [];
  let currentChunk: { heading?: string; content: string } = { content: '' };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Check if this is a heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      // Save previous chunk if it has content
      if (currentChunk.content.trim()) {
        chunks.push(currentChunk);
      }
      // Start new chunk with heading
      currentChunk = {
        heading: headingMatch[2],
        content: line + '\n',
      };
    } else {
      currentChunk.content += line + '\n';
    }
  }

  // Don't forget the last chunk
  if (currentChunk.content.trim()) {
    chunks.push(currentChunk);
  }

  return chunks;
}

// Determine chunk kind based on heading content and context
function inferChunkKind(
  heading?: string,
  content: string = '',
  documentKind: DocumentKind
): ChunkKind {
  if (!heading) {
    // For frontmatter summary or intro
    if (content.includes('---') && content.includes('course') && documentKind === 'syllabus') {
      return 'summary';
    }
    return 'overview';
  }

  const h = heading.toLowerCase();

  if (h.includes('objective') || h.includes('goal')) {
    return 'objective';
  }
  if (h.includes('motivation') || h.includes('why')) {
    return 'motivation';
  }
  if (h.includes('definition') || h.includes('define')) {
    return 'definition';
  }
  if (h.includes('theorem') || h.includes('lemma') || h.includes('proposition')) {
    return 'theorem';
  }
  if (h.includes('proof') || h.includes('proof of')) {
    return 'proof';
  }
  if (h.includes('example') || h.includes('illustration')) {
    return 'example';
  }
  if (h.includes('exercise') || h.includes('problem') || h.includes('question')) {
    return 'exercise';
  }
  if (h.includes('misconception') || h.includes('common mistake') || h.includes('confusion')) {
    return 'misconception';
  }
  if (h.includes('summary') || h.includes('recap') || h.includes('conclusion')) {
    return 'summary';
  }
  if (h.includes('reflection') || h.includes('thoughts')) {
    return 'reflection';
  }
  if (h.includes('faq') || h.includes('?')) {
    return 'faq';
  }

  // Default based on document type
  if (documentKind === 'concept') {
    return 'definition';
  }
  if (documentKind === 'lesson') {
    return 'overview';
  }

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
    const { attributes } = parse(content);

    // You could use path.basename without extension as a default ID
    const filename = path.basename(filePath);
    const idFromFile = path.basename(filename, path.extname(filename));

    let doc: DocumentEntry = {
      id: '',
      path: relativePath,
      kind,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      checksum: checksum(content),
    };

    // Type-specific parsing
    switch (kind) {
      case 'lesson':
        const lesson = attributes as LessonFrontmatter;
        doc.id = lesson.id || idFromFile;
        doc.title = lesson.title;
        doc.lessonId = lesson.id;
        doc.conceptId = undefined;
        doc.unit = lesson.unit;
        break;

      case 'concept':
        const concept = attributes as ConceptFrontmatter;
        doc.id = concept.id || idFromFile;
        doc.title = concept.title;
        doc.conceptId = concept.id;
        doc.lessonId = undefined;
        doc.unit = undefined;
        break;

      case 'syllabus':
        doc.id = 'syllabus';
        doc.title = 'Syllabus';
        break;

      case 'manifest':
        doc.id = 'manifest';
        doc.title = 'Course Manifest';
        break;

      case 'state':
        // For state files like mastery.yaml
        doc.id = path.basename(relativePath, '.yaml');
        doc.title = doc.id;
        break;

      case 'assignment':
        doc.id = idFromFile;
        doc.title = (attributes as { title?: string }).title || doc.id;
        break;

      case 'session_log':
        doc.id = idFromFile;
        doc.title = (attributes as { title?: string }).title || doc.id;
        break;

      case 'config':
        doc.id = idFromFile;
        doc.title = doc.id;
        break;
    }

    return doc;
  } catch (error) {
    console.error(`Failed to parse ${filePath}:`, error);
    return null;
  }
}

// Main function: given a document entry and content, produce chunks
export function extractChunks(
  doc: DocumentEntry,
  content: string
): ChunkEntry[] {
  const chunks: ChunkEntry[] = [];

  // If it's not a markdown file, treat as a single chunk
  if (!path.basename(doc.path).endsWith('.md')) {
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

  // Parse frontmatter + markdown body
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

  // Then split the markdown body
  const markdownChunks = splitByHeadings(body);

  for (let i = 0; i < markdownChunks.length; i++) {
    const { heading, content: chunkContent } = markdownChunks[i];
    const chunkKind = inferChunkKind(heading, chunkContent, doc.kind);

    // Generate a stable chunk ID
    const chunkId = heading
      ? `${doc.id}:${heading.toLowerCase().replace(/\s+/g, '-')}-${i}`
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

// File discovery
export async function discoverFiles(
  workspaceRoot: string,
  patterns: string[]
): Promise<string[]> {
  // For now, simple recursive walk
  const allFiles: string[] = [];

  async function walk(dir: string): Promise<void> {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name);
        const matchesPattern = patterns.some((pattern) => {
          if (pattern.endsWith('/*')) {
            return entry.name.endsWith(pattern.slice(0, -2));
          }
          return pattern === entry.name || pattern.endsWith(ext);
        });
        if (matchesPattern) {
          allFiles.push(fullPath);
        }
      }
    }
  }

  await walk(workspaceRoot);
  return allFiles;
}
