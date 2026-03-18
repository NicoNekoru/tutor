import path from 'path';
import { promises as fs } from 'fs';
import { v4 as uuidv4 } from 'uuid';
import { WorkspaceManager } from '../workspace/WorkspaceManager';
import { SQLiteDatabase } from './Database';
import {
  DocumentKind,
  DocumentEntry,
  ChunkEntry,
  ChunkTag,
  ConceptEdge,
} from '../schemas/types';
import {
  discoverFiles,
  extractDocumentEntry,
  extractChunks,
  estimateTokens,
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

    // Discover files based on known patterns
    const files = await discoverFiles(workspaceRoot, [
      '**/*.md',
      '**/*.yaml',
      '**/*.yml',
      '**/manifest.yaml',
      '**/syllabus.md',
      '**/configs/*.yaml',
      '**/lessons/*.md',
      '**/concepts/*.md',
      '**/assignments/*.md',
      '**/logs/**/*.md',
      '**/state/*.yaml',
    ]);

    console.log(`Found ${files.length} files to index`);

    try {
      for (const filePath of files) {
        await this.indexFile(workspaceRoot, filePath);
      }

      console.log('Indexing completed successfully');
    } catch (error) {
      console.error('Indexing failed:', error);
      throw error;
    }
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

        // Extract and store tags from chunk content (simple keyword extraction)
        const tags = this.extractTags(chunk);
        for (const tag of tags) {
          this.db.addChunkTag(chunk.id, tag);
        }
      }

      // If document has concept info, update concept edges
      if (kind === 'concept' && doc.conceptId) {
        this.indexConceptEdges(doc.id, relativePath, content);
      }
    }
  }

  private inferDocumentKind(relativePath: string): DocumentKind {
    const parts = relativePath.split(path.sep);

    if (parts.includes('configs')) {
      return 'config';
    }
    if (parts.includes('lessons')) {
      return 'lesson';
    }
    if (parts.includes('concepts')) {
      return 'concept';
    }
    if (parts.includes('assignments')) {
      return 'assignment';
    }
    if (parts.includes('logs')) {
      if (parts.includes('sessions')) {
        return 'session_log';
      }
      return 'session_log'; // summaries are also logs
    }
    if (parts.includes('state')) {
      return 'state';
    }
    if (relativePath === 'manifest.yaml' || path.basename(relativePath) === 'manifest.yaml') {
      return 'manifest';
    }
    if (relativePath === 'syllabus.md' || path.basename(relativePath) === 'syllabus.md') {
      return 'syllabus';
    }

    return 'config'; // default fallback
  }

  private extractTags(chunk: ChunkEntry): string[] {
    const tags: string[] = [];

    // Add chunk kind as a tag
    tags.push(`kind:${chunk.chunkKind}`);

    // Extract potential concept tags from ID
    if (chunk.documentId.includes(':')) {
      const conceptPart = chunk.documentId.split(':')[0];
      tags.push(`concept:${conceptPart}`);
    }

    // Extract any hashtags from content (simple regex)
    const hashtagRegex = /#([a-zA-Z0-9_-]+)/g;
    let match;
    while ((match = hashtagRegex.exec(chunk.content)) !== null) {
      tags.push(match[1].toLowerCase());
    }

    return tags;
  }

  private indexConceptEdges(
    conceptId: string,
    filePath: string,
    content: string
  ): void {
    // Parse concept frontmatter to get prerequisites and related
    const { attributes } = parse(content);
    const conceptAttrs = attributes as any;

    if (conceptAttrs.prerequisites) {
      for (const prereq of conceptAttrs.prerequisites) {
        this.db.upsertConceptEdge({
          sourceConceptId: conceptId,
          relation: 'prerequisite',
          targetConceptId: prereq,
        });
      }
    }

    if (conceptAttrs.related) {
      for (const related of conceptAttrs.related) {
        this.db.upsertConceptEdge({
          sourceConceptId: conceptId,
          relation: 'related',
          targetConceptId: related,
        });
      }
    }
  }

  async reindex(workspaceRoot: string): Promise<void> {
    // Clear all data and re-index
    console.log('Clearing existing index...');
    this.db.exec('DELETE FROM chunk_tags');
    this.db.exec('DELETE FROM concept_edges');
    this.db.exec('DELETE FROM chunks');
    this.db.exec('DELETE FROM documents');
    // Reset autoincrement not needed as we use UUIDs

    await this.indexWorkspace(workspaceRoot);
  }
}
