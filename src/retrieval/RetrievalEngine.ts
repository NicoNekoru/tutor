import { SQLiteDatabase } from '../indexer/Database';
import {
  SearchResult,
  RetrievalFilters,
  ChunkKind,
  DocumentKind,
} from '../schemas/types';

export class RetrievalEngine {
  private db: SQLiteDatabase;

  constructor(db: SQLiteDatabase) {
    this.db = db;
  }

  search(
    query: string,
    options: {
      filters?: RetrievalFilters;
      topK?: number;
      includeScores?: boolean;
    } = {}
  ): SearchResult[] {
    const { filters = {}, topK = 10, includeScores = true } = options;

    let results = this.db.searchFullText(query, filters);

    // Apply ranking boosts
    results = this.applyRankingBoosts(results, query, filters);

    // Sort by score (descending, higher is better)
    results.sort((a, b) => b.score - a.score);

    // Return top K
    return results.slice(0, topK).map((r) => ({
      chunkId: r.chunkId,
      documentId: r.documentId,
      path: r.path,
      score: r.score,
      chunkKind: r.chunkKind,
      heading: r.heading,
      contentPreview: r.contentPreview,
      tags: r.tags,
    }));
  }

  private applyRankingBoosts(
    results: SearchResult[],
    query: string,
    filters: RetrievalFilters
  ): SearchResult[] {
    // Simple scoring: lexical + metadata/structural + recency + mastery
    // This is a placeholder for a more sophisticated ranking later

    for (const result of results) {
      let score = result.score;

      // Boost if chunk is from current lesson (if lessonId filter matches)
      if (filters.lessonId && result.documentId.includes(filters.lessonId)) {
        score += 2.0;
      }

      // Boost if chunk is a relevant kind for query
      if (this.isRelevantChunkKind(result.chunkKind, query)) {
        score += 1.5;
      }

      // Boost if result has tags matching query keywords
      const queryKeywords = query.toLowerCase().split(/\s+/);
      for (const tag of result.tags) {
        if (queryKeywords.some((kw) => tag.includes(kw))) {
          score += 0.5;
          break;
        }
      }

      result.score = score;
    }

    return results;
  }

  private isRelevantChunkKind(kind: ChunkKind, query: string): boolean {
    const q = query.toLowerCase();

    // If query is about definitions or concepts
    if (q.includes('what is') || q.includes('define') || q.includes('meaning')) {
      return ['definition', 'overview', 'summary'].includes(kind);
    }

    // If query is about examples
    if (q.includes('example') || q.includes('illustrate')) {
      return ['example', 'exercise'].includes(kind);
    }

    // If query is about proofs
    if (q.includes('proof') || q.includes('show that') || q.includes('prove')) {
      return ['proof', 'theorem'].includes(kind);
    }

    // If query mentions misconception or confusion
    if (q.includes('confus') || q.includes('misconception') || q.includes('wrong')) {
      return ['misconception'].includes(kind);
    }

    return true; // default: all kinds potentially relevant
  }

  getChunk(chunkId: string): SearchResult | null {
    // We don't have direct chunk lookup in current DB schema
    // Could add a helper method or query
    return null;
  }

  getDocumentChunks(documentId: string): SearchResult[] {
    // This would query chunks by documentId and return them as SearchResult-like objects
    // Not implemented in minimal version
    return [];
  }

  // Get chunks related to a concept via graph edges
  async getConceptNeighbors(conceptId: string, relation?: string): Promise<string[]> {
    // Query concept edges
    // Implementation depends on adding a method to Database
    return [];
  }

  // Get recent session logs
  getRecentLogs(limit: number = 5): Array<{ id: string; title: string; date: string }> {
    // Query session logs, ordered by date
    // Not fully implemented; placeholder
    return [];
  }
}
