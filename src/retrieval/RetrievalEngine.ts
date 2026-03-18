import { IndexStore } from '../indexer/IndexStore';
import {
  SearchResult,
  RetrievalFilters,
  ChunkKind,
  DocumentKind,
} from '../schemas/types';

export class RetrievalEngine {
  private store: IndexStore;

  constructor(store: IndexStore) {
    this.store = store;
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

    let results = this.store.searchFullText(query, filters);

    // Apply ranking boosts
    results = this.applyRankingBoosts(results, query, filters);

    // Sort by score (descending, higher is better)
    results.sort((a, b) => b.score - a.score);

    // Return top K
    return results.slice(0, topK).map((r) => ({
      chunkId: r.chunkId,
      documentId: r.documentId,
      path: r.path,
      score: includeScores ? r.score : undefined,
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
    for (const result of results) {
      let score = result.score;

      // Boost if chunk is from current lesson
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

    if (q.includes('what is') || q.includes('define') || q.includes('meaning')) {
      return ['definition', 'overview', 'summary'].includes(kind);
    }

    if (q.includes('example') || q.includes('illustrate')) {
      return ['example', 'exercise'].includes(kind);
    }

    if (q.includes('proof') || q.includes('show that') || q.includes('prove')) {
      return ['proof', 'theorem'].includes(kind);
    }

    if (q.includes('confus') || q.includes('misconception') || q.includes('wrong')) {
      return ['misconception'].includes(kind);
    }

    return true;
  }

  getChunk(chunkId: string): SearchResult | null {
    const chunk = this.store.getChunkById(chunkId);
    if (!chunk) return null;

    const doc = this.store.getDocumentById(chunk.documentId);
    if (!doc) return null;

    return {
      chunkId: chunk.id,
      documentId: chunk.documentId,
      path: doc.path,
      score: 0,
      chunkKind: chunk.chunkKind,
      heading: chunk.heading,
      contentPreview: chunk.content.substring(0, 200) + '...',
      tags: this.store.getChunkTags(chunkId),
    };
  }
}
