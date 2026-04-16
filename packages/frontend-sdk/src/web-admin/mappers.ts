import {
  asRecord,
  getNumber,
  getOptionalString,
  getString,
  getStringArray
} from '../core/utils';
import type {
  AdminDiagnosticPayload,
  AdminDiagnosticSource,
  AdminSearchPreviewItem,
  AdminSearchPreviewPayload,
  CountBucket,
  RetrievalCitation
} from './types';

function mapAdminSearchPreviewItem(value: unknown): AdminSearchPreviewItem {
  const record = asRecord(value);
  return {
    docId: getString(record, ['doc_id', 'docId']),
    chunkId: getString(record, ['chunk_id', 'chunkId']),
    kbId: getOptionalString(record, ['kb_id', 'kbId']) ?? null,
    title: getString(record, ['title']),
    score: getNumber(record, ['score']),
    contentPreview: getString(record, ['content_preview', 'contentPreview']),
    sourceType: getOptionalString(record, ['source_type', 'sourceType']) ?? null,
    tags: getStringArray(record.tags)
  };
}

function mapAdminDiagnosticSource(value: unknown): AdminDiagnosticSource {
  return mapAdminSearchPreviewItem(value);
}

function mapCountBucket(value: unknown): CountBucket {
  const record = asRecord(value);
  return {
    label: getString(record, ['label']),
    count: getNumber(record, ['count'])
  };
}

function mapRetrievalCitation(value: unknown): RetrievalCitation {
  const record = asRecord(value);
  return {
    chunkId: getString(record, ['chunk_id', 'chunkId']),
    sourceId: getString(record, ['source_id', 'sourceId']),
    sourceName: getString(record, ['source_name', 'sourceName']),
    documentId: getString(record, ['document_id', 'documentId', 'doc_id', 'docId']),
    documentTitle: getString(record, ['document_title', 'documentTitle', 'title']),
    snippet: getString(record, ['snippet']),
    score: getNumber(record, ['score']),
    reasoning: getString(record, ['reasoning'])
  };
}

export function mapAdminSearchPreviewPayload(value: unknown): AdminSearchPreviewPayload {
  const record = asRecord(value);
  return {
    query: getString(record, ['query']),
    rewrittenQuery: getOptionalString(record, ['rewritten_query', 'rewrittenQuery']) ?? null,
    total: getNumber(record, ['total']),
    degraded: Boolean(record.degraded),
    items: Array.isArray(record.items) ? record.items.map(mapAdminSearchPreviewItem) : []
  };
}

export function mapAdminDiagnosticPayload(value: unknown): AdminDiagnosticPayload {
  const record = asRecord(value);
  const coverage = asRecord(record.coverage);
  const debug = asRecord(record.debug);
  const appliedFilters = asRecord(debug.applied_filters ?? debug.appliedFilters);
  const sourceBreakdown = coverage.source_breakdown ?? coverage.sourceBreakdown;
  const tagBreakdown = coverage.tag_breakdown ?? coverage.tagBreakdown;

  return {
    query: getString(record, ['query']),
    rewrittenQuery: getString(record, ['rewritten_query', 'rewrittenQuery']),
    sources: Array.isArray(record.sources) ? record.sources.map(mapAdminDiagnosticSource) : [],
    coverage: {
      candidateCount: getNumber(coverage, ['candidate_count', 'candidateCount']),
      sourceBreakdown: Array.isArray(sourceBreakdown)
        ? sourceBreakdown.map((item: unknown) => {
            const source = asRecord(item);
            return {
              sourceId: getString(source, ['source_id', 'sourceId']),
              sourceName: getString(source, ['source_name', 'sourceName']),
              hitCount: getNumber(source, ['hit_count', 'hitCount']),
              bestScore: getNumber(source, ['best_score', 'bestScore'])
            };
          })
        : [],
      tagBreakdown: Array.isArray(tagBreakdown)
        ? tagBreakdown.map(mapCountBucket)
        : [],
      unmatchedTerms: getStringArray(coverage.unmatched_terms ?? coverage.unmatchedTerms),
      degraded: Boolean(coverage.degraded)
    },
    answerable: Boolean(record.answerable),
    debug: {
      expandedTerms: getStringArray(debug.expanded_terms ?? debug.expandedTerms),
      queryTerms: getStringArray(debug.query_terms ?? debug.queryTerms),
      appliedFilters: {
        sourceIds: getStringArray(appliedFilters.source_ids ?? appliedFilters.sourceIds),
        tags: getStringArray(appliedFilters.tags)
      },
      citations: Array.isArray(debug.citations) ? debug.citations.map(mapRetrievalCitation) : []
    },
    notes: getStringArray(record.notes)
  };
}
