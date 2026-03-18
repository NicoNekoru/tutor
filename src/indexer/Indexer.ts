import path from 'path';
import { promises as fs } from 'fs';
import parse from 'front-matter';
import { WorkspaceManager } from '../workspace/WorkspaceManager';
import { SQLiteDatabase } from './Database';
import {
  ChunkEntry,
} from '../schemas/types';
import {
  discoverFiles,
  extractDocumentEntry,
  extractChunks,
} from './ChunkExtractor';

export class Indexer {
  private db: SQLiteDatabase;
  private ws: WorkspaceManager;

  constructor(db: SQLiteDatabase, ws: WorkspaceManager) {
    this.db = db;
    this.ws = ws;
  }

  async indexWorkspace(workspaceRoot: string): Promise<void> {
    console.log('Indexing workspace...');

    const files = await discoverFiles(workspaceRoot);

    console.log(`Found ${files.length} files to index`);

    for (const filePath of files) {
      await this.indexFile(workspaceRoot, filePath);
    }

    console.log('Indexing completed successfully');
  }

  private async indexFile(
    workspaceRoot: string,
    absolutePath: string
  ): Promise<void> {
    const relativePath = path.relative(workspaceRoot, absolutePath);
    const content = await fs.readFile(absolutePath, 'utf-8');

    // Determine document kind from path
    const kind = this.inferDocumentKind(relativePath);

    // Extract document entry
    const doc = extractDocumentEntry(absolutePath, relativePath, content, kind);
    if (!doc) {
      console.warn(`Skipping ${relativePath}: could not parse document`);
      return;
    }

    // Update timestamps
    const stats = await fs.stat(absolutePath);
    doc.createdAt = new Date(stats.mtime).toISOString();
    doc.updatedAt = new Date(stats.mtime).toISOString();

    // Store document
    this.db.upsertDocument(doc);

    // Delete old chunks for this document
    this.db.deleteChunksByDocumentId(doc.id);

    // Extract and store chunks (for markdown files)
    if (absolutePath.endsWith('.md')) {
      const chunks = extractChunks(doc, content);

      for (const chunk of chunks) {
        this.db.upsertChunk(chunk);

        // Extract and store tags from chunk content
        const tags = this.extractTags(chunk);
        for (const tag of tags) {
          this.db.addChunkTag(chunk.id, tag);
        }
      }

      // If document has concept info, update concept edges
      if (kind === 'concept' && doc.conceptId) {
        this.indexConceptEdges(doc.conceptId, content);
      }
    }
  }

  private inferDocumentKind(relativePath: string) {
    const parts = relativePath.split(path.sep);

    if (parts.includes('configs')) return 'config' as const;
    if (parts.includes('lessons')) return 'lesson' as const;
    if (parts.includes('concepts')) return 'concept' as const;
    if (parts.includes('assignments')) return 'assignment' as const;
    if (parts.includes('logs')) return 'session_log' as const;
    if (parts.includes('state')) return 'state' as const;
    if (path.basename(relativePath) === 'manifest.yaml') return 'manifest' as const;
    if (path.basename(relativePath) === 'syllabus.md') return 'syllabus' as const;

    return 'config' as const;
  }

  private extractTags(chunk: ChunkEntry): string[] {
    const tags: string[] = [];

    // Add chunk kind as a tag
    tags.push(`kind:${chunk.chunkKind}`);

    // Extract any hashtags from content
    const hashtagRegex = /#([a-zA-Z0-9_-]+)/g;
    let match;
    while ((match = hashtagRegex.exec(chunk.content)) !== null) {
      tags.push(match[1].toLowerCase());
    }

    return tags;
  }

  private indexConceptEdges(conceptId: string, content: string): void {
    try {
      const { attributes } = parse(content);
      const attrs = attributes as Record<string, any>;

      if (Array.isArray(attrs.prerequisites)) {
        for (const prereq of attrs.prerequisites) {
          this.db.upsertConceptEdge({
            source_concept_id: conceptId,
            relation: 'prerequisite',
            target_concept_id: prereq,
          });
        }
      }

      if (Array.isArray(attrs.related)) {
        for (const related of attrs.related) {
          this.db.upsertConceptEdge({
            source_concept_id: conceptId,
            relation: 'related',
            target_concept_id: related,
          });
        }
      }
    } catch {
      // Skip if frontmatter parsing fails
    }
  }

  async reindex(workspaceRoot: string): Promise<void> {
    console.log('Clearing existing index...');
    this.db.exec('DELETE FROM chunk_tags');
    this.db.exec('DELETE FROM concept_edges');
    this.db.exec('DELETE FROM chunks');
    this.db.exec('DELETE FROM documents');

    await this.indexWorkspace(workspaceRoot);
  }
}
