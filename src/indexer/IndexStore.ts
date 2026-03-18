import { promises as fs } from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import {
  DocumentKind,
  ChunkKind,
  DocumentEntry,
  ChunkEntry,
  SearchResult,
  RetrievalFilters,
} from '../schemas/types';

interface IndexData {
  documents: Map<string, DocumentEntry>;
  chunks: Map<string, ChunkEntry>;
  chunkTags: Map<string, string[]>;
  conceptEdges: Array<{ source_concept_id: string; relation: string; target_concept_id: string }>;
  events: Array<{ id: string; event_type: string; created_at: string; payload_json: string }>;
  retrievalLog: Array<{ id: string; created_at: string; query: string; filters_json: string; selected_chunk_ids_json: string; notes?: string }>;
}

export class IndexStore {
  private data: IndexData;
  private storePath: string;

  constructor() {
    this.data = {
      documents: new Map(),
      chunks: new Map(),
      chunkTags: new Map(),
      conceptEdges: [],
      events: [],
      retrievalLog: [],
    };
    this.storePath = '';
  }

  async initialize(storePath: string): Promise<void> {
    this.storePath = storePath;
    await this.load();
  }

  async save(): Promise<void> {
    if (!this.storePath) return;

    const dir = path.dirname(this.storePath);
    await fs.mkdir(dir, { recursive: true });

    const serializable = {
      documents: Array.from(this.data.documents.entries()),
      chunks: Array.from(this.data.chunks.entries()),
      chunkTags: Array.from(this.data.chunkTags.entries()),
      conceptEdges: this.data.conceptEdges,
      events: this.data.events,
      retrievalLog: this.data.retrievalLog,
    };

    await fs.writeFile(this.storePath, JSON.stringify(serializable, null, 2), 'utf-8');
  }

  private async load(): Promise<void> {
    try {
      const content = await fs.readFile(this.storePath, 'utf-8');
      const loaded = JSON.parse(content);

      this.data.documents = new Map(loaded.documents);
      this.data.chunks = new Map(loaded.chunks);
      this.data.chunkTags = new Map(loaded.chunkTags);
      this.data.conceptEdges = loaded.conceptEdges || [];
      this.data.events = loaded.events || [];
      this.data.retrievalLog = loaded.retrievalLog || [];
    } catch (error) {
      // File doesn't exist or is invalid; start fresh
      console.log('No existing index found, starting fresh');
    }
  }

  // Document operations
  upsertDocument(doc: DocumentEntry): void {
    this.data.documents.set(doc.id, doc);
  }

  getDocumentById(id: string): DocumentEntry | null {
    return this.data.documents.get(id) || null;
  }

  getDocumentByPath(path: string): DocumentEntry | null {
    for (const doc of this.data.documents.values()) {
      if (doc.path === path) return doc;
    }
    return null;
  }

  getAllDocuments(): DocumentEntry[] {
    return Array.from(this.data.documents.values());
  }

  deleteDocumentsByPath(paths: string[]): void {
    const docIdsToDelete = new Set<string>();
    for (const [id, doc] of this.data.documents.entries()) {
      if (paths.includes(doc.path)) {
        docIdsToDelete.add(id);
      }
    }
    for (const id of docIdsToDelete) {
      this.data.documents.delete(id);
    }
  }

  // Chunk operations
  upsertChunk(chunk: ChunkEntry): void {
    this.data.chunks.set(chunk.id, chunk);
  }

  getChunksByDocumentId(documentId: string): ChunkEntry[] {
    const chunks: ChunkEntry[] = [];
    for (const chunk of this.data.chunks.values()) {
      if (chunk.documentId === documentId) {
        chunks.push(chunk);
      }
    }
    return chunks.sort((a, b) => a.ordinal - b.ordinal);
  }

  getChunkById(id: string): ChunkEntry | null {
    return this.data.chunks.get(id) || null;
  }

  deleteChunksByDocumentId(documentId: string): void {
    const chunkIdsToDelete = new Set<string>();
    for (const [id, chunk] of this.data.chunks.entries()) {
      if (chunk.documentId === documentId) {
        chunkIdsToDelete.add(id);
      }
    }
    for (const id of chunkIdsToDelete) {
      this.data.chunks.delete(id);
      this.data.chunkTags.delete(id);
    }
  }

  // Chunk tags
  addChunkTag(chunkId: string, tag: string): void {
    const tags = this.data.chunkTags.get(chunkId) || [];
    if (!tags.includes(tag)) {
      tags.push(tag);
      this.data.chunkTags.set(chunkId, tags);
    }
  }

  getChunkTags(chunkId: string): string[] {
    return this.data.chunkTags.get(chunkId) || [];
  }

  // Concept edges
  upsertConceptEdge(edge: { source_concept_id: string; relation: string; target_concept_id: string }): void {
    // Remove existing edges with same source/relation/target
    this.data.conceptEdges = this.data.conceptEdges.filter(
      (e) => !(e.source_concept_id === edge.source_concept_id && e.relation === edge.relation && e.target_concept_id === edge.target_concept_id)
    );
    this.data.conceptEdges.push(edge);
  }

  getConceptEdges(sourceConceptId?: string): Array<{ source_concept_id: string; relation: string; target_concept_id: string }> {
    if (sourceConceptId) {
      return this.data.conceptEdges.filter((e) => e.source_concept_id === sourceConceptId);
    }
    return this.data.conceptEdges;
  }

  deleteConceptEdgesBySource(sourceConceptId: string): void {
    this.data.conceptEdges = this.data.conceptEdges.filter((e) => e.source_concept_id !== sourceConceptId);
  }

  // Events
  logEvent(event: { id: string; event_type: string; created_at: string; payload_json: string }): void {
    this.data.events.push(event);
  }

  getEvents(limit: number = 100): Array<{ id: string; event_type: string; created_at: string; payload_json: string }> {
    return this.data.events.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, limit);
  }

  // Retrieval log
  logRetrieval(log: { id: string; created_at: string; query: string; filters_json: string; selected_chunk_ids_json: string; notes?: string }): void {
    this.data.retrievalLog.push(log);
  }

  // Search
  searchFullText(
    query: string,
    filters?: {
      kinds?: DocumentKind[];
      lessonId?: string;
      conceptIds?: string[];
      tags?: string[];
    }
  ): Array<{
    chunkId: string;
    documentId: string;
    path: string;
    score: number;
    chunkKind: ChunkKind;
    heading?: string;
    contentPreview: string;
    tags: string[];
  }> {
    const queryLower = query.toLowerCase();
    const results: Array<{
      chunk: ChunkEntry;
      document: DocumentEntry;
      score: number;
    }> = [];

    for (const chunk of this.data.chunks.values()) {
      const doc = this.data.documents.get(chunk.documentId);
      if (!doc) continue;

      // Apply filters
      if (filters?.kinds?.length && !filters.kinds.includes(doc.kind)) {
        continue;
      }
      if (filters?.lessonId && doc.lessonId !== filters.lessonId) {
        continue;
      }
      if (filters?.conceptIds?.length && (!doc.conceptId || !filters.conceptIds.includes(doc.conceptId))) {
        continue;
      }
      if (filters?.tags?.length) {
        const chunkTags = this.data.chunkTags.get(chunk.id) || [];
        const hasAllTags = filters.tags.every((tag) => chunkTags.includes(tag));
        if (!hasAllTags) continue;
      }

      // Simple text matching
      const contentLower = chunk.content.toLowerCase();
      if (contentLower.includes(queryLower)) {
        // Simple scoring: count occurrences and position
        const occurrences = (contentLower.match(new RegExp(queryLower, 'g')) || []).length;
        const position = contentLower.indexOf(queryLower);
        const score = occurrences * 10 - position * 0.1; // Higher score for more matches, earlier position

        results.push({ chunk, document: doc, score });
      }
    }

    // Sort by score descending
    results.sort((a, b) => b.score - a.score);

    // Return formatted results
    return results.map((r) => ({
      chunkId: r.chunk.id,
      documentId: r.document.id,
      path: r.document.path,
      score: r.score,
      chunkKind: r.chunk.chunkKind,
      heading: r.chunk.heading,
      contentPreview: r.chunk.content.substring(0, 200) + '...',
      tags: this.data.chunkTags.get(r.chunk.id) || [],
    }));
  }

  clearAll(): void {
    this.data.documents.clear();
    this.data.chunks.clear();
    this.data.chunkTags.clear();
    this.data.conceptEdges = [];
    this.data.events = [];
    this.data.retrievalLog = [];
  }
}
