// @ts-ignore - sql.js doesn't ship types
import initSqlJs from 'sql.js';
import { promises as fs } from 'fs';
import path from 'path';
import { DocumentKind, ChunkKind } from '../schemas/types';

let SQL: any = null;

export class SQLiteDatabase {
  private db!: any;
  private dbPath?: string;

  constructor(dbPath?: string) {
    this.dbPath = dbPath;
  }

  async initialize(): Promise<void> {
    if (!SQL) {
      SQL = await initSqlJs();
    }

    if (this.dbPath) {
      try {
        const buffer = await fs.readFile(this.dbPath);
        this.db = new SQL.Database(buffer);
      } catch {
        // File doesn't exist yet, create new database
        this.db = new SQL.Database();
      }
    } else {
      this.db = new SQL.Database();
    }

    this.createSchema();
  }

  private createSchema(): void {
    this.db.run(`
      CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        title TEXT,
        lesson_id TEXT,
        concept_id TEXT,
        unit TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        checksum TEXT NOT NULL
      );

      CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind);
      CREATE INDEX IF NOT EXISTS idx_documents_lesson_id ON documents(lesson_id);
      CREATE INDEX IF NOT EXISTS idx_documents_concept_id ON documents(concept_id);

      CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        chunk_kind TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        heading TEXT,
        content TEXT NOT NULL,
        token_estimate INTEGER,
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

      CREATE TABLE IF NOT EXISTS chunk_tags (
        chunk_id TEXT NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (chunk_id, tag),
        FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
      );

      CREATE INDEX IF NOT EXISTS idx_chunk_tags_chunk_id ON chunk_tags(chunk_id);
      CREATE INDEX IF NOT EXISTS idx_chunk_tags_tag ON chunk_tags(tag);

      CREATE TABLE IF NOT EXISTS concept_edges (
        source_concept_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        target_concept_id TEXT NOT NULL,
        PRIMARY KEY (source_concept_id, relation, target_concept_id)
      );

      CREATE INDEX IF NOT EXISTS idx_concept_edges_source ON concept_edges(source_concept_id);
      CREATE INDEX IF NOT EXISTS idx_concept_edges_target ON concept_edges(target_concept_id);

      CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
      );

      CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
      CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);

      CREATE TABLE IF NOT EXISTS retrieval_log (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        query TEXT NOT NULL,
        filters_json TEXT,
        selected_chunk_ids_json TEXT NOT NULL,
        notes TEXT
      );

      CREATE INDEX IF NOT EXISTS idx_retrieval_created_at ON retrieval_log(created_at);
    `);
  }

  async save(): Promise<void> {
    if (this.dbPath) {
      const data = this.db.export();
      const buffer = Buffer.from(data);
      await fs.mkdir(path.dirname(this.dbPath), { recursive: true });
      await fs.writeFile(this.dbPath, buffer);
    }
  }

  exec(sql: string): void {
    this.db.run(sql);
  }

  run(sql: string, params: any[] = []): void {
    this.db.run(sql, params);
  }

  get<T>(sql: string, params: any[] = []): T | null {
    const stmt = this.db.prepare(sql);
    stmt.bind(params);
    if (stmt.step()) {
      const row = stmt.getAsObject();
      stmt.free();
      return row as T;
    }
    stmt.free();
    return null;
  }

  all<T>(sql: string, params: any[] = []): T[] {
    const stmt = this.db.prepare(sql);
    stmt.bind(params);
    const results: T[] = [];
    while (stmt.step()) {
      results.push(stmt.getAsObject() as T);
    }
    stmt.free();
    return results;
  }

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
    let sql = `
      SELECT c.id as chunk_id, c.document_id, d.path, d.kind, c.chunk_kind, c.heading, c.content
      FROM chunks c
      JOIN documents d ON c.document_id = d.id
      WHERE c.content LIKE ?
    `;
    const params: any[] = [`%${query}%`];

    if (filters?.kinds?.length) {
      const placeholders = filters.kinds.map(() => '?').join(',');
      sql += ` AND d.kind IN (${placeholders})`;
      params.push(...filters.kinds);
    }

    if (filters?.lessonId) {
      sql += ' AND d.lesson_id = ?';
      params.push(filters.lessonId);
    }

    if (filters?.conceptIds?.length) {
      const placeholders = filters.conceptIds.map(() => '?').join(',');
      sql += ` AND d.concept_id IN (${placeholders})`;
      params.push(...filters.conceptIds);
    }

    sql += ' LIMIT 50';

    const rows = this.all<any>(sql, params);
    return rows.map((row: any) => {
      const chunkId = row.chunk_id as string;
      const tags = this.getChunkTags(chunkId);
      return {
        chunkId,
        documentId: row.document_id as string,
        path: row.path as string,
        score: 0,
        chunkKind: row.chunk_kind as ChunkKind,
        heading: (row.heading as string) || undefined,
        contentPreview: (row.content as string).substring(0, 200),
        tags,
      };
    });
  }

  getChunkTags(chunkId: string): string[] {
    const rows = this.all<{ tag: string }>(
      'SELECT tag FROM chunk_tags WHERE chunk_id = ?',
      [chunkId]
    );
    return rows.map((r) => r.tag);
  }

  addChunkTag(chunkId: string, tag: string): void {
    this.run('INSERT OR IGNORE INTO chunk_tags (chunk_id, tag) VALUES (?, ?)', [
      chunkId,
      tag,
    ]);
  }

  getConceptEdges(sourceConceptId?: string): Array<{ source_concept_id: string; relation: string; target_concept_id: string }> {
    if (sourceConceptId) {
      return this.all('SELECT * FROM concept_edges WHERE source_concept_id = ?', [sourceConceptId]);
    }
    return this.all('SELECT * FROM concept_edges');
  }

  upsertConceptEdge(edge: { source_concept_id: string; relation: string; target_concept_id: string }): void {
    this.run(
      'INSERT OR REPLACE INTO concept_edges (source_concept_id, relation, target_concept_id) VALUES (?, ?, ?)',
      [edge.source_concept_id, edge.relation, edge.target_concept_id]
    );
  }

  logEvent(event: { id: string; eventType: string; createdAt: string; payloadJson: string }): void {
    this.run(
      'INSERT INTO events (id, event_type, created_at, payload_json) VALUES (?, ?, ?, ?)',
      [event.id, event.eventType, event.createdAt, event.payloadJson]
    );
  }

  logRetrieval(log: { id: string; createdAt: string; query: string; filtersJson: string; selectedChunkIdsJson: string; notes?: string }): void {
    this.run(
      'INSERT INTO retrieval_log (id, created_at, query, filters_json, selected_chunk_ids_json, notes) VALUES (?, ?, ?, ?, ?, ?)',
      [log.id, log.createdAt, log.query, log.filtersJson, log.selectedChunkIdsJson, log.notes ?? null]
    );
  }

  upsertDocument(doc: any): void {
    const now = new Date().toISOString();
    this.run(
      `INSERT OR REPLACE INTO documents (id, path, kind, title, lesson_id, concept_id, unit, created_at, updated_at, checksum)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [doc.id, doc.path, doc.kind, doc.title ?? null, doc.lessonId ?? null, doc.conceptId ?? null, doc.unit ?? null, doc.createdAt ?? now, doc.updatedAt ?? now, doc.checksum]
    );
  }

  getAllDocuments(): any[] {
    return this.all('SELECT * FROM documents');
  }

  upsertChunk(chunk: any): void {
    this.run(
      `INSERT OR REPLACE INTO chunks (id, document_id, chunk_kind, ordinal, heading, content, token_estimate)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [chunk.id, chunk.documentId, chunk.chunkKind, chunk.ordinal, chunk.heading ?? null, chunk.content, chunk.tokenEstimate]
    );
  }

  deleteChunksByDocumentId(documentId: string): void {
    // First delete tags for chunks of this document
    this.run('DELETE FROM chunk_tags WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id = ?)', [documentId]);
    this.run('DELETE FROM chunks WHERE document_id = ?', [documentId]);
  }

  deleteDocumentsByPath(paths: string[]): void {
    const placeholders = paths.map(() => '?').join(',');
    this.run(`DELETE FROM documents WHERE path IN (${placeholders})`, paths);
  }
}
