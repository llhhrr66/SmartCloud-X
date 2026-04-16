import { startTransition, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { AdminAuditPanel } from "./components/AdminAuditPanel";
import { ActivityFeed } from "./components/ActivityFeed";
import { CitationList } from "./components/CitationList";
import { ChunkTable } from "./components/ChunkTable";
import { DocumentDetailPanel } from "./components/DocumentDetailPanel";
import { DocumentTable } from "./components/DocumentTable";
import { FileImportPanel } from "./components/FileImportPanel";
import { HealthCard } from "./components/HealthCard";
import { IntegrationStatusPanel } from "./components/IntegrationStatusPanel";
import { KnowledgeBaseSettingsPanel } from "./components/KnowledgeBaseSettingsPanel";
import { KnowledgeSearchPanel } from "./components/KnowledgeSearchPanel";
import { OverviewPanel } from "./components/OverviewPanel";
import { SourceTable } from "./components/SourceTable";
import {
  answer,
  bootstrapCatalog,
  createKnowledgeBase,
  createKnowledgeDocument,
  diagnose,
  diagnoseAdminRetrieval,
  fetchAdminJob,
  fetchKnowledgeAuditRecords,
  fetchChunks,
  fetchKnowledgeBaseDocuments,
  fetchKnowledgeDocumentDetail,
  fetchKnowledgeBases,
  fetchDocuments,
  fetchIngestions,
  fetchKnowledgeHealth,
  fetchKnowledgeSnapshot,
  fetchOverview,
  fetchRagCapabilities,
  fetchRagHealth,
  fetchSources,
  importFiles,
  ingestDocument,
  previewImportFiles,
  reindexKnowledgeDocument,
  searchKnowledgeAdminPreview,
  searchKnowledge,
  updateKnowledgeBase,
} from "./lib/api";
import type {
  AdminDiagnosticPayload,
  AdminAsyncJob,
  AdminAuditRecord,
  AdminDocumentDetailPayload,
  AdminDocumentRecord,
  AdminSearchPreviewPayload,
  AnswerPayload,
  BootstrapPayload,
  ChunkRecord,
  DocumentRecord,
  FileImportPayload,
  FileImportPreviewPayload,
  HealthPayload,
  IngestionJob,
  IngestionResult,
  KnowledgeBaseRecord,
  KnowledgeRuntimeSnapshot,
  KnowledgeSearchPayload,
  KnowledgeOverview,
  RagCapabilities,
  RetrievalDiagnosticPayload,
  SourceRecord,
} from "./types";

const initialForm = {
  sourceName: "产品文档库",
  sourceKind: "manual",
  sourceUri: "ops://gpu-baseline",
  sourceDescription: "产品发布与运维基线知识",
  sourceTags: "product, docs",
  title: "GPU 云主机上架说明",
  tags: "gpu, launch",
  content:
    "GPU 云主机支持训练与推理负载。上架时应说明实例规格、驱动版本、镜像适配、网络带宽和扩容策略。",
};

const initialKnowledgeBaseForm = {
  name: "GPU 基线知识库",
  code: "gpu-baseline",
  scene: "product",
  language: "zh-CN",
  retrievalMode: "hybrid-baseline",
  embeddingModel: "baseline-keyword",
  description: "供管理员验证知识导入、检索与重建索引的基线知识库。",
};

const initialKnowledgeBaseSettingsForm = {
  name: "",
  description: "",
  retrievalMode: "hybrid-baseline",
  status: "ready" as "ready" | "disabled",
};

const initialFileImportForm = {
  directory: "starter",
  glob: "**/*",
  tags: "filesystem, starter",
};

function parseCsv(input: string): string[] {
  return input
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function snapshotFileStamp(isoTimestamp: string): string {
  return isoTimestamp.replace(/[:]/g, "-").replace(/\+/g, "-");
}

function downloadJsonFile(fileName: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}

export default function App() {
  const [knowledgeHealth, setKnowledgeHealth] = useState<HealthPayload | null>(null);
  const [ragHealth, setRagHealth] = useState<HealthPayload | null>(null);
  const [overview, setOverview] = useState<KnowledgeOverview | null>(null);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseRecord[]>([]);
  const [documents, setDocuments] = useState<AdminDocumentRecord[]>([]);
  const [rawDocuments, setRawDocuments] = useState<DocumentRecord[]>([]);
  const [chunks, setChunks] = useState<ChunkRecord[]>([]);
  const [ingestions, setIngestions] = useState<IngestionJob[]>([]);
  const [auditRecords, setAuditRecords] = useState<AdminAuditRecord[]>([]);
  const [ingestState, setIngestState] = useState<IngestionResult | null>(null);
  const [bootstrapState, setBootstrapState] = useState<BootstrapPayload | null>(null);
  const [filePreviewState, setFilePreviewState] = useState<FileImportPreviewPayload | null>(null);
  const [fileImportState, setFileImportState] = useState<FileImportPayload | null>(null);
  const [searchState, setSearchState] = useState<KnowledgeSearchPayload | null>(null);
  const [adminSearchState, setAdminSearchState] = useState<AdminSearchPreviewPayload | null>(null);
  const [retrievalState, setRetrievalState] = useState<RetrievalDiagnosticPayload | null>(null);
  const [adminDiagnosticState, setAdminDiagnosticState] = useState<AdminDiagnosticPayload | null>(null);
  const [answerState, setAnswerState] = useState<AnswerPayload | null>(null);
  const [ragCapabilities, setRagCapabilities] = useState<RagCapabilities | null>(null);
  const [knowledgeBaseState, setKnowledgeBaseState] = useState<KnowledgeBaseRecord | null>(null);
  const [adminDocumentState, setAdminDocumentState] = useState<AdminDocumentRecord | null>(null);
  const [reindexState, setReindexState] = useState<AdminAsyncJob | null>(null);
  const [selectedDocumentDetail, setSelectedDocumentDetail] = useState<AdminDocumentDetailPayload | null>(null);
  const [selectedDocumentJob, setSelectedDocumentJob] = useState<AdminAsyncJob | null>(null);
  const [snapshotState, setSnapshotState] = useState<{
    exportedAt: string;
    fileName: string;
    auditCount: number;
    knowledgeBaseCount: number;
    documentCount: number;
  } | null>(null);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<KnowledgeRuntimeSnapshot | null>(null);
  const [query, setQuery] = useState("GPU 部署前需要确认什么");
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [retrievalKnowledgeBaseId, setRetrievalKnowledgeBaseId] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [auditResourceType, setAuditResourceType] = useState("");
  const [auditAction, setAuditAction] = useState("");
  const [auditOperatorId, setAuditOperatorId] = useState("");
  const [activeAdminDocumentFileId, setActiveAdminDocumentFileId] = useState<string | null>(null);
  const [filterTags, setFilterTags] = useState("gpu, launch");
  const [form, setForm] = useState(initialForm);
  const [knowledgeBaseForm, setKnowledgeBaseForm] = useState(initialKnowledgeBaseForm);
  const [knowledgeBaseSettingsForm, setKnowledgeBaseSettingsForm] = useState(
    initialKnowledgeBaseSettingsForm,
  );
  const [fileImportForm, setFileImportForm] = useState(initialFileImportForm);
  const [operatorReason, setOperatorReason] = useState("baseline-operator-validation");
  const [confirmToken, setConfirmToken] = useState("");
  const [loading, setLoading] = useState({
    health: true,
    overview: true,
    sources: true,
    knowledgeBases: true,
    documents: true,
    documentDetail: false,
    documentJob: false,
    chunks: false,
    ingestions: true,
    audit: true,
    ingest: false,
    createKnowledgeBase: false,
    updateKnowledgeBase: false,
    createAdminDocument: false,
    reindex: false,
    bootstrap: false,
    previewFiles: false,
    importFiles: false,
    search: false,
    retrieve: false,
    answer: false,
    capabilities: false,
    snapshot: false,
    snapshotSummary: true,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (documents.length === 0) {
      setSelectedDocumentId("");
      setChunks([]);
      return;
    }
    if (!selectedDocumentId || !documents.some((document) => document.doc_id === selectedDocumentId)) {
      setSelectedDocumentId(documents[0].doc_id);
    }
  }, [documents, selectedDocumentId]);

  useEffect(() => {
    if (knowledgeBases.length === 0) {
      setSelectedKnowledgeBaseId("");
      setRetrievalKnowledgeBaseId("");
      return;
    }
    if (
      !selectedKnowledgeBaseId ||
      !knowledgeBases.some((knowledgeBase) => knowledgeBase.kb_id === selectedKnowledgeBaseId)
    ) {
      setSelectedKnowledgeBaseId(knowledgeBases[0].kb_id);
    }
    if (
      retrievalKnowledgeBaseId &&
      !knowledgeBases.some((knowledgeBase) => knowledgeBase.kb_id === retrievalKnowledgeBaseId)
    ) {
      setRetrievalKnowledgeBaseId("");
    }
  }, [knowledgeBases, selectedKnowledgeBaseId, retrievalKnowledgeBaseId]);

  useEffect(() => {
    const selectedKnowledgeBase = knowledgeBases.find(
      (knowledgeBase) => knowledgeBase.kb_id === selectedKnowledgeBaseId,
    );
    if (!selectedKnowledgeBase) {
      setKnowledgeBaseSettingsForm(initialKnowledgeBaseSettingsForm);
      return;
    }
    setKnowledgeBaseSettingsForm({
      name: selectedKnowledgeBase.name,
      description: selectedKnowledgeBase.description ?? "",
      retrievalMode: selectedKnowledgeBase.retrieval_mode,
      status: selectedKnowledgeBase.status === "disabled" ? "disabled" : "ready",
    });
  }, [knowledgeBases, selectedKnowledgeBaseId]);

  useEffect(() => {
    setConfirmToken(selectedDocumentId ? `reindex:${selectedDocumentId}` : "");
  }, [selectedDocumentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadChunks() {
      if (!selectedDocumentId) {
        setChunks([]);
        return;
      }
      setLoading((current) => ({ ...current, chunks: true }));
      try {
        const result = await fetchChunks(selectedDocumentId);
        if (!cancelled) {
          startTransition(() => {
            setChunks(result);
          });
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Chunk fetch failed");
          setChunks([]);
        }
      } finally {
        if (!cancelled) {
          setLoading((current) => ({ ...current, chunks: false }));
        }
      }
    }

    void loadChunks();
    return () => {
      cancelled = true;
    };
  }, [selectedDocumentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadSelectedDocumentDetail() {
      if (!selectedDocumentId) {
        setSelectedDocumentDetail(null);
        setSelectedDocumentJob(null);
        return;
      }

      setLoading((current) => ({ ...current, documentDetail: true, documentJob: true }));
      setSelectedDocumentDetail(null);
      setSelectedDocumentJob(null);
      try {
        const detail = await fetchKnowledgeDocumentDetail(selectedDocumentId);
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setSelectedDocumentDetail(detail);
        });

        const latestJobId = detail.chunk_stats.latest_job_id;
        if (!latestJobId) {
          if (!cancelled) {
            setSelectedDocumentJob(null);
          }
          return;
        }

        const job = await fetchAdminJob(latestJobId);
        if (!cancelled) {
          startTransition(() => {
            setSelectedDocumentJob(job);
          });
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Document detail fetch failed");
          setSelectedDocumentDetail(null);
          setSelectedDocumentJob(null);
        }
      } finally {
        if (!cancelled) {
          setLoading((current) => ({ ...current, documentDetail: false, documentJob: false }));
        }
      }
    }

    void loadSelectedDocumentDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedDocumentId]);

  useEffect(() => {
    let cancelled = false;

    async function loadAdminDocuments() {
      if (!selectedKnowledgeBaseId) {
        setDocuments([]);
        return;
      }
      setLoading((current) => ({ ...current, documents: true }));
      try {
        const result = await fetchKnowledgeBaseDocuments(selectedKnowledgeBaseId);
        if (!cancelled) {
          startTransition(() => {
            setDocuments(result.items);
          });
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Document fetch failed");
          setDocuments([]);
        }
      } finally {
        if (!cancelled) {
          setLoading((current) => ({ ...current, documents: false }));
        }
      }
    }

    void loadAdminDocuments();
    return () => {
      cancelled = true;
    };
  }, [selectedKnowledgeBaseId]);

  useEffect(() => {
    void loadAuditRecords({
      resourceType: auditResourceType,
      action: auditAction,
      operatorId: auditOperatorId,
    });
  }, [auditAction, auditOperatorId, auditResourceType]);

  async function loadAuditRecords(filters?: {
    resourceType?: string;
    action?: string;
    operatorId?: string;
  }) {
    setLoading((current) => ({ ...current, audit: true }));
    try {
      const resourceType = filters?.resourceType ?? auditResourceType;
      const action = filters?.action ?? auditAction;
      const operatorId = filters?.operatorId ?? auditOperatorId;
      const result = await fetchKnowledgeAuditRecords({
        page: 1,
        pageSize: 10,
        resourceType: resourceType || undefined,
        action: action || undefined,
        operatorId: operatorId || undefined,
      });
      startTransition(() => {
        setAuditRecords(result.items);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Audit fetch failed");
      setAuditRecords([]);
    } finally {
      setLoading((current) => ({ ...current, audit: false }));
    }
  }

  async function refreshAll() {
    setError(null);
    setLoading((current) => ({
      ...current,
      health: true,
      overview: true,
      sources: true,
      knowledgeBases: true,
      documents: true,
      ingestions: true,
      capabilities: true,
      snapshotSummary: true,
    }));
    const [
      knowledgeResult,
      ragResult,
      capabilitiesResult,
      overviewResult,
      sourcesResult,
      knowledgeBaseResult,
      rawDocumentsResult,
      ingestionsResult,
      snapshotResult,
    ] = await Promise.allSettled([
      fetchKnowledgeHealth(),
      fetchRagHealth(),
      fetchRagCapabilities(),
      fetchOverview(),
      fetchSources(),
      fetchKnowledgeBases(),
      fetchDocuments(),
      fetchIngestions(),
      fetchKnowledgeSnapshot(5),
    ]);

    let adminDocumentsResult:
      | PromiseSettledResult<Awaited<ReturnType<typeof fetchKnowledgeBaseDocuments>>>
      | null = null;
    if (knowledgeBaseResult.status === "fulfilled" && knowledgeBaseResult.value.items.length > 0) {
      const fallbackKnowledgeBaseId =
        selectedKnowledgeBaseId && knowledgeBaseResult.value.items.some((item) => item.kb_id === selectedKnowledgeBaseId)
          ? selectedKnowledgeBaseId
          : knowledgeBaseResult.value.items[0].kb_id;
      adminDocumentsResult = await Promise.allSettled([
        fetchKnowledgeBaseDocuments(fallbackKnowledgeBaseId),
      ]).then((results) => results[0]);
    }

    const failures: string[] = [];
    startTransition(() => {
      if (knowledgeResult.status === "fulfilled") {
        setKnowledgeHealth(knowledgeResult.value);
      } else {
        failures.push(
          knowledgeResult.reason instanceof Error
            ? knowledgeResult.reason.message
            : "Knowledge health failed",
        );
      }

      if (ragResult.status === "fulfilled") {
        setRagHealth(ragResult.value);
      } else {
        failures.push(
          ragResult.reason instanceof Error ? ragResult.reason.message : "RAG health failed",
        );
      }

      if (capabilitiesResult.status === "fulfilled") {
        setRagCapabilities(capabilitiesResult.value);
      } else {
        failures.push(
          capabilitiesResult.reason instanceof Error
            ? capabilitiesResult.reason.message
            : "RAG capability fetch failed",
        );
      }

      if (overviewResult.status === "fulfilled") {
        setOverview(overviewResult.value);
      } else {
        failures.push(
          overviewResult.reason instanceof Error
            ? overviewResult.reason.message
            : "Overview fetch failed",
        );
      }

      if (sourcesResult.status === "fulfilled") {
        setSources(sourcesResult.value);
      } else {
        failures.push(
          sourcesResult.reason instanceof Error ? sourcesResult.reason.message : "Source fetch failed",
        );
      }

      if (knowledgeBaseResult.status === "fulfilled") {
        setKnowledgeBases(knowledgeBaseResult.value.items);
        const nextKnowledgeBaseId =
          selectedKnowledgeBaseId &&
          knowledgeBaseResult.value.items.some((item) => item.kb_id === selectedKnowledgeBaseId)
            ? selectedKnowledgeBaseId
            : knowledgeBaseResult.value.items[0]?.kb_id ?? "";
        setSelectedKnowledgeBaseId(nextKnowledgeBaseId);
      } else {
        failures.push(
          knowledgeBaseResult.reason instanceof Error
            ? knowledgeBaseResult.reason.message
            : "Knowledge base fetch failed",
        );
      }

      if (rawDocumentsResult.status === "fulfilled") {
        setRawDocuments(rawDocumentsResult.value);
      } else {
        failures.push(
          rawDocumentsResult.reason instanceof Error
            ? rawDocumentsResult.reason.message
            : "Document fetch failed",
        );
      }

      if (adminDocumentsResult?.status === "fulfilled") {
        setDocuments(adminDocumentsResult.value.items);
      } else if (knowledgeBaseResult.status === "fulfilled" && knowledgeBaseResult.value.items.length > 0) {
        failures.push(
          adminDocumentsResult?.reason instanceof Error
            ? adminDocumentsResult.reason.message
            : "Admin document fetch failed",
        );
        setDocuments([]);
      } else {
        setDocuments([]);
      }

      if (ingestionsResult.status === "fulfilled") {
        setIngestions(ingestionsResult.value);
      } else {
        failures.push(
          ingestionsResult.reason instanceof Error
            ? ingestionsResult.reason.message
            : "Ingestion fetch failed",
        );
      }

      if (snapshotResult.status === "fulfilled") {
        setRuntimeSnapshot(snapshotResult.value);
      } else {
        failures.push(
          snapshotResult.reason instanceof Error
            ? snapshotResult.reason.message
            : "Snapshot fetch failed",
        );
      }

      setError(failures.length > 0 ? failures.join(" | ") : null);
      setLoading((current) => ({
        ...current,
        health: false,
        overview: false,
        sources: false,
        knowledgeBases: false,
        documents: false,
        ingestions: false,
        capabilities: false,
        snapshotSummary: false,
      }));
    });
  }

  async function handleIngest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading((current) => ({ ...current, ingest: true }));
    try {
      const result = await ingestDocument({
        sourceId: selectedKnowledgeBaseId || undefined,
        sourceName: form.sourceName,
        sourceKind: form.sourceKind,
        sourceUri: form.sourceUri,
        sourceDescription: form.sourceDescription,
        sourceTags: parseCsv(form.sourceTags),
        title: form.title,
        tags: parseCsv(form.tags),
        content: form.content,
      });
      startTransition(() => {
        setIngestState(result);
        setSelectedDocumentId(result.document.id);
      });
      await refreshAll();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Ingestion failed");
    } finally {
      setLoading((current) => ({ ...current, ingest: false }));
    }
  }

  async function handleCreateKnowledgeBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading((current) => ({ ...current, createKnowledgeBase: true }));
    try {
      const result = await createKnowledgeBase({
        ...knowledgeBaseForm,
        operatorReason,
      });
      startTransition(() => {
        setKnowledgeBaseState(result);
        setSelectedKnowledgeBaseId(result.kb_id);
      });
      await refreshAll();
      await loadAuditRecords();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Knowledge base creation failed");
    } finally {
      setLoading((current) => ({ ...current, createKnowledgeBase: false }));
    }
  }

  async function handleUpdateKnowledgeBase() {
    if (!selectedKnowledgeBaseId) {
      setError("Select a knowledge base before saving settings.");
      return;
    }
    setError(null);
    setLoading((current) => ({ ...current, updateKnowledgeBase: true }));
    try {
      const result = await updateKnowledgeBase({
        knowledgeBaseId: selectedKnowledgeBaseId,
        name: knowledgeBaseSettingsForm.name,
        description: knowledgeBaseSettingsForm.description,
        retrievalMode: knowledgeBaseSettingsForm.retrievalMode,
        status: knowledgeBaseSettingsForm.status,
        operatorReason,
      });
      startTransition(() => {
        setKnowledgeBaseState(result);
      });
      await refreshAll();
      await loadAuditRecords();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Knowledge base update failed");
    } finally {
      setLoading((current) => ({ ...current, updateKnowledgeBase: false }));
    }
  }

  async function handleDownloadSnapshot() {
    setError(null);
    setLoading((current) => ({ ...current, snapshot: true }));
    try {
      const snapshot: KnowledgeRuntimeSnapshot = await fetchKnowledgeSnapshot(25);
      const fileName = `knowledge-runtime-snapshot-${snapshotFileStamp(snapshot.exportedAt)}.json`;
      downloadJsonFile(fileName, snapshot);
      startTransition(() => {
        setRuntimeSnapshot(snapshot);
        setSnapshotState({
          exportedAt: snapshot.exportedAt,
          fileName,
          auditCount: snapshot.recentAuditRecords.length,
          knowledgeBaseCount:
            snapshot.counts.knowledgeBases ?? snapshot.knowledgeBases.length,
          documentCount: snapshot.counts.documents ?? snapshot.documents.length,
        });
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Snapshot export failed");
    } finally {
      setLoading((current) => ({ ...current, snapshot: false }));
    }
  }

  async function handleCreateAdminDocument(fileId: string, title: string) {
    if (!selectedKnowledgeBaseId) {
      setError("Select a knowledge base before creating an admin document.");
      return;
    }
    setError(null);
    setActiveAdminDocumentFileId(fileId);
    setLoading((current) => ({ ...current, createAdminDocument: true }));
    try {
      const result = await createKnowledgeDocument({
        knowledgeBaseId: selectedKnowledgeBaseId,
        fileId,
        title,
        tags: parseCsv(fileImportForm.tags),
        sourceType: "filesystem",
        operatorReason,
      });
      startTransition(() => {
        setAdminDocumentState(result);
        setSelectedDocumentId(result.doc_id);
      });
      await refreshAll();
      await loadAuditRecords();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Admin document creation failed");
    } finally {
      setLoading((current) => ({ ...current, createAdminDocument: false }));
      setActiveAdminDocumentFileId(null);
    }
  }

  async function handleBootstrap() {
    setError(null);
    setLoading((current) => ({ ...current, bootstrap: true }));
    try {
      const result = await bootstrapCatalog({
        operatorReason
      });
      startTransition(() => {
        setBootstrapState(result);
      });
      await refreshAll();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Starter catalog bootstrap failed");
    } finally {
      setLoading((current) => ({ ...current, bootstrap: false }));
    }
  }

  async function handlePreviewFiles() {
    setError(null);
    setLoading((current) => ({ ...current, previewFiles: true }));
    try {
      const result = await previewImportFiles(fileImportForm.directory, fileImportForm.glob, 12);
      startTransition(() => {
        setFilePreviewState(result);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Filesystem preview failed");
    } finally {
      setLoading((current) => ({ ...current, previewFiles: false }));
    }
  }

  async function handleImportFiles() {
    setError(null);
    setLoading((current) => ({ ...current, importFiles: true }));
    try {
      const result = await importFiles({
        directory: fileImportForm.directory,
        glob: fileImportForm.glob,
        maxFiles: 12,
        sourceId: selectedKnowledgeBaseId || undefined,
        sourceName: form.sourceName,
        sourceKind: form.sourceKind,
        sourceUri: form.sourceUri,
        sourceDescription: form.sourceDescription,
        sourceTags: parseCsv(form.sourceTags),
        tags: parseCsv(fileImportForm.tags),
      });
      startTransition(() => {
        setFileImportState(result);
        const firstDocumentId = result.results.find((item) => item.documentId)?.documentId;
        if (firstDocumentId) {
          setSelectedDocumentId(firstDocumentId);
        }
      });
      await refreshAll();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Filesystem import failed");
    } finally {
      setLoading((current) => ({ ...current, importFiles: false }));
    }
  }

  async function handleReindexDocument() {
    if (!selectedDocumentId) {
      setError("Select a document before requesting reindex.");
      return;
    }
    setError(null);
    setLoading((current) => ({ ...current, reindex: true }));
    try {
      const result = await reindexKnowledgeDocument({
        documentId: selectedDocumentId,
        confirmToken,
        operatorReason,
      });
      startTransition(() => {
        setReindexState(result);
      });
      await refreshAll();
      await loadAuditRecords();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Document reindex failed");
    } finally {
      setLoading((current) => ({ ...current, reindex: false }));
    }
  }

  async function handleRetrieve() {
    setError(null);
    setLoading((current) => ({ ...current, retrieve: true }));
    try {
      const [result, adminResult] = await Promise.all([
        diagnose(
          query,
          5,
          retrievalKnowledgeBaseId ? [retrievalKnowledgeBaseId] : [],
          parseCsv(filterTags),
        ),
        diagnoseAdminRetrieval(query, 5, retrievalKnowledgeBaseId || undefined),
      ]);
      startTransition(() => {
        setRetrievalState(result);
        setAdminDiagnosticState(adminResult);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Diagnostic failed");
    } finally {
      setLoading((current) => ({ ...current, retrieve: false }));
    }
  }

  async function handleSearchPreview() {
    setError(null);
    setLoading((current) => ({ ...current, search: true }));
    try {
      const tags = parseCsv(filterTags);
      const [result, adminResult] = await Promise.all([
        searchKnowledge(
          query,
          5,
          retrievalKnowledgeBaseId ? [retrievalKnowledgeBaseId] : [],
          tags,
        ),
        searchKnowledgeAdminPreview(query, 5, retrievalKnowledgeBaseId || undefined, tags),
      ]);
      startTransition(() => {
        setSearchState(result);
        setAdminSearchState(adminResult);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Knowledge search failed");
    } finally {
      setLoading((current) => ({ ...current, search: false }));
    }
  }

  async function handleAnswer() {
    setError(null);
    setLoading((current) => ({ ...current, answer: true }));
    try {
      const tags = parseCsv(filterTags);
      const result = await answer(
        query,
        5,
        retrievalKnowledgeBaseId ? [retrievalKnowledgeBaseId] : [],
        tags,
      );
      startTransition(() => {
        setAnswerState(result);
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Answer failed");
    } finally {
      setLoading((current) => ({ ...current, answer: false }));
    }
  }

  const knowledgeBaseCount = knowledgeBases.length;
  const effectiveSourceCount = overview?.counts.sources ?? sources.length;
  const documentCount = overview?.counts.documents ?? rawDocuments.length;
  const ingestionCount = overview?.counts.ingestions ?? ingestions.length;
  const selectedKnowledgeBase =
    knowledgeBases.find((knowledgeBase) => knowledgeBase.kb_id === selectedKnowledgeBaseId) ?? null;
  const selectedDocument = rawDocuments.find((document) => document.id === selectedDocumentId) ?? null;

  return (
    <main className="app-shell">
      <section className="hero panel">
        <div>
          <div className="eyebrow">SmartCloud-X</div>
          <h1>Knowledge + RAG Operations Console</h1>
          <p>
            Create admin knowledge bases, seed documents, inspect retrieval behavior, and
            verify service health before wiring the full supervisor stack.
          </p>
          <div className="summary-row">
            <span className="summary-chip">{knowledgeBaseCount} knowledge bases</span>
            <span className="summary-chip">{effectiveSourceCount} sources</span>
            <span className="summary-chip">{documentCount} documents</span>
            <span className="summary-chip">{ingestionCount} ingestion jobs</span>
          </div>
          {snapshotState ? (
            <div className="note-box">
              Latest runtime snapshot: {snapshotState.fileName} exported{" "}
              {new Date(snapshotState.exportedAt).toLocaleString()} with{" "}
              {snapshotState.knowledgeBaseCount} knowledge bases, {snapshotState.documentCount} documents,
              and {snapshotState.auditCount} recent audit records.
            </div>
          ) : null}
        </div>
        <div className="hero-actions">
          <button className="action-button" onClick={() => void handleBootstrap()} disabled={loading.bootstrap}>
            {loading.bootstrap ? "Seeding..." : "Seed Starter Catalog"}
          </button>
          <button
            className="ghost-button"
            onClick={() => void handleDownloadSnapshot()}
            disabled={loading.snapshot}
          >
            {loading.snapshot ? "Exporting..." : "Export Runtime Snapshot"}
          </button>
          <button className="ghost-button" onClick={() => void refreshAll()}>
            Refresh
          </button>
        </div>
      </section>

      {error ? <div className="error-banner">{error}</div> : null}

      <section className="grid two-up">
        <HealthCard label="Knowledge Service" payload={knowledgeHealth} loading={loading.health} />
        <HealthCard label="RAG Service" payload={ragHealth} loading={loading.health} />
      </section>

      <section className="grid">
        <OverviewPanel payload={overview} loading={loading.overview} />
      </section>

      <section className="grid">
        <IntegrationStatusPanel snapshot={runtimeSnapshot} loading={loading.snapshotSummary} />
      </section>

      <section className="grid two-up">
        <section className="panel">
          <div className="section-header">
            <div>
              <div className="eyebrow">Admin Write Paths</div>
              <h2>Knowledge Base + Ingestion Controls</h2>
            </div>
            {ingestState ? <span className="pill">{ingestState.chunksCreated} chunks</span> : null}
          </div>
          {knowledgeBaseState ? (
            <div className="note-box">
              Latest knowledge base state: {knowledgeBaseState.name} ({knowledgeBaseState.code}) is
              {" "}
              {knowledgeBaseState.status} with {knowledgeBaseState.document_count} docs and
              {" "}
              {knowledgeBaseState.chunk_count} chunks.
            </div>
          ) : null}
          {adminDocumentState ? (
            <div className="note-box">
              Latest admin document: {adminDocumentState.title} now tracks {adminDocumentState.chunk_count} chunks
              in KB {adminDocumentState.kb_id}.
            </div>
          ) : null}
          {reindexState ? (
            <div className="note-box">
              Reindex job {reindexState.job_id} finished with status {reindexState.status}.
            </div>
          ) : null}
          {bootstrapState ? (
            <div className="note-box">
              Starter catalog: {bootstrapState.seededDocuments} seeded, {bootstrapState.reusedDocuments} reused,
              now tracking {bootstrapState.documentCount} documents across {bootstrapState.sourceCount} sources.
            </div>
          ) : null}
          <form className="stack-form" onSubmit={handleCreateKnowledgeBase}>
            <div className="inline-inputs">
              <label>
                <span>KB Name</span>
                <input
                  value={knowledgeBaseForm.name}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, name: event.target.value })
                  }
                />
              </label>
              <label>
                <span>KB Code</span>
                <input
                  value={knowledgeBaseForm.code}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, code: event.target.value })
                  }
                />
              </label>
            </div>
            <div className="inline-inputs">
              <label>
                <span>Scene</span>
                <input
                  value={knowledgeBaseForm.scene}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, scene: event.target.value })
                  }
                />
              </label>
              <label>
                <span>Language</span>
                <input
                  value={knowledgeBaseForm.language}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, language: event.target.value })
                  }
                />
              </label>
            </div>
            <div className="inline-inputs">
              <label>
                <span>Retrieval Mode</span>
                <input
                  value={knowledgeBaseForm.retrievalMode}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, retrievalMode: event.target.value })
                  }
                />
              </label>
              <label>
                <span>Embedding Model</span>
                <input
                  value={knowledgeBaseForm.embeddingModel}
                  onChange={(event) =>
                    setKnowledgeBaseForm({ ...knowledgeBaseForm, embeddingModel: event.target.value })
                  }
                />
              </label>
            </div>
            <label>
              <span>Description</span>
              <input
                value={knowledgeBaseForm.description}
                onChange={(event) =>
                  setKnowledgeBaseForm({ ...knowledgeBaseForm, description: event.target.value })
                }
              />
            </label>
            <label>
              <span>Operator Reason</span>
              <input
                value={operatorReason}
                onChange={(event) => setOperatorReason(event.target.value)}
              />
            </label>
            <button type="submit" className="ghost-button" disabled={loading.createKnowledgeBase}>
              {loading.createKnowledgeBase ? "Creating KB..." : "Create Knowledge Base"}
            </button>
          </form>
          <form className="stack-form" onSubmit={handleIngest}>
            <div className="inline-inputs">
              <label>
                <span>Target Knowledge Base</span>
                <select
                  value={selectedKnowledgeBaseId}
                  onChange={(event) => setSelectedKnowledgeBaseId(event.target.value)}
                >
                  <option value="">Create a new source from the fields below</option>
                  {knowledgeBases.map((knowledgeBase) => (
                    <option key={knowledgeBase.kb_id} value={knowledgeBase.kb_id}>
                      {knowledgeBase.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Operator Reason</span>
                <input
                  value={operatorReason}
                  onChange={(event) => setOperatorReason(event.target.value)}
                />
              </label>
            </div>
            <div className="inline-inputs">
              <label>
                <span>Source Name</span>
                <input
                  value={form.sourceName}
                  onChange={(event) => setForm({ ...form, sourceName: event.target.value })}
                />
              </label>
              <label>
                <span>Source Kind</span>
                <input
                  value={form.sourceKind}
                  onChange={(event) => setForm({ ...form, sourceKind: event.target.value })}
                />
              </label>
            </div>
            <div className="inline-inputs">
              <label>
                <span>Source URI</span>
                <input
                  value={form.sourceUri}
                  onChange={(event) => setForm({ ...form, sourceUri: event.target.value })}
                />
              </label>
              <label>
                <span>Source Tags</span>
                <input
                  value={form.sourceTags}
                  onChange={(event) => setForm({ ...form, sourceTags: event.target.value })}
                />
              </label>
            </div>
            <label>
              <span>Source Description</span>
              <input
                value={form.sourceDescription}
                onChange={(event) => setForm({ ...form, sourceDescription: event.target.value })}
              />
            </label>
            <label>
              <span>Document Title</span>
              <input
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
              />
            </label>
            <label>
              <span>Document Tags</span>
              <input
                value={form.tags}
                onChange={(event) => setForm({ ...form, tags: event.target.value })}
              />
            </label>
            <label>
              <span>Content</span>
              <textarea
                rows={8}
                value={form.content}
                onChange={(event) => setForm({ ...form, content: event.target.value })}
              />
            </label>
            <button type="submit" className="action-button" disabled={loading.ingest}>
              {loading.ingest ? "Ingesting..." : "Ingest Document"}
            </button>
          </form>
          {ingestState?.job.warnings.length ? (
            <p className="warning-note">Last ingestion note: {ingestState.job.warnings.join(", ")}</p>
          ) : null}

          <div className="result-stack">
            <section className="result-box">
              <div className="section-header compact">
                <div>
                  <div className="eyebrow">Filesystem Batch Import</div>
                  <h2>Import Markdown/Text Files</h2>
                </div>
              </div>
              <p className="service-note">
                Reuses the source metadata above and scans the server-side import root for markdown/text files.
              </p>
              <div className="inline-inputs">
                <label>
                  <span>Directory</span>
                  <input
                    value={fileImportForm.directory}
                    onChange={(event) =>
                      setFileImportForm({ ...fileImportForm, directory: event.target.value })
                    }
                    placeholder="starter"
                  />
                </label>
                <label>
                  <span>Glob</span>
                  <input
                    value={fileImportForm.glob}
                    onChange={(event) =>
                      setFileImportForm({ ...fileImportForm, glob: event.target.value })
                    }
                    placeholder="**/*"
                  />
                </label>
              </div>
              <label>
                <span>Batch Tags</span>
                <input
                  value={fileImportForm.tags}
                  onChange={(event) =>
                    setFileImportForm({ ...fileImportForm, tags: event.target.value })
                  }
                  placeholder="filesystem, starter"
                />
              </label>
              <div className="button-row">
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => void handlePreviewFiles()}
                  disabled={loading.previewFiles}
                >
                  {loading.previewFiles ? "Scanning..." : "Preview Files"}
                </button>
                <button
                  type="button"
                  className="action-button"
                  onClick={() => void handleImportFiles()}
                  disabled={loading.importFiles}
                >
                  {loading.importFiles ? "Importing..." : "Import Files"}
                </button>
              </div>
            </section>
            <FileImportPanel
              preview={filePreviewState}
              importState={fileImportState}
              previewLoading={loading.previewFiles}
              importLoading={loading.importFiles}
              selectedKnowledgeBaseId={selectedKnowledgeBaseId}
              adminDocumentLoading={loading.createAdminDocument}
              adminDocumentFileId={activeAdminDocumentFileId}
              onCreateAdminDocument={(item) => void handleCreateAdminDocument(item.path, item.title)}
            />
          </div>
        </section>

        <section className="panel">
          <div className="section-header">
            <div>
              <div className="eyebrow">Playground</div>
              <h2>Retrieval Diagnostics</h2>
            </div>
          </div>
          <div className="stack-form">
            <div className="inline-inputs">
              <label>
                <span>Knowledge Base Scope</span>
                <select
                  value={retrievalKnowledgeBaseId}
                  onChange={(event) => setRetrievalKnowledgeBaseId(event.target.value)}
                >
                  <option value="">All knowledge bases</option>
                  {knowledgeBases.map((knowledgeBase) => (
                    <option key={knowledgeBase.kb_id} value={knowledgeBase.kb_id}>
                      {knowledgeBase.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Tag Filter</span>
                <input
                  value={filterTags}
                  onChange={(event) => setFilterTags(event.target.value)}
                  placeholder="gpu, launch"
                />
              </label>
            </div>
            <label>
              <span>Operator Query</span>
              <textarea rows={4} value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            {ragCapabilities ? (
              <div className="badge-list">
                <span className="badge">rewrite: {ragCapabilities.rewrite}</span>
                <span className="badge badge-secondary">retrieval: {ragCapabilities.retrieval}</span>
                <span className="badge badge-secondary">rerank: {ragCapabilities.rerank}</span>
                <span className="badge badge-secondary">answering: {ragCapabilities.answering}</span>
                <span className="badge badge-secondary">diagnostics: {ragCapabilities.diagnostics}</span>
                {ragCapabilities.cache ? (
                  <span className="badge">cache: {ragCapabilities.cache}</span>
                ) : null}
              </div>
            ) : null}
          </div>
          <div className="button-row">
            <button
              className="ghost-button"
              onClick={() => void handleSearchPreview()}
              disabled={loading.search}
            >
              {loading.search ? "Searching..." : "Preview Knowledge Search"}
            </button>
            <button className="action-button" onClick={() => void handleRetrieve()} disabled={loading.retrieve}>
              {loading.retrieve ? "Diagnosing..." : "Run Diagnostic"}
            </button>
            <button className="ghost-button" onClick={() => void handleAnswer()} disabled={loading.answer}>
              {loading.answer ? "Composing..." : "Compose Answer"}
            </button>
          </div>

          <div className="result-stack">
            <KnowledgeSearchPanel payload={searchState} loading={loading.search} />
            <section className="result-box">
              <div className="section-header compact">
                <div>
                  <div className="eyebrow">Canonical Admin Route</div>
                  <h2>Admin Search Preview</h2>
                </div>
                <span className="pill">
                  {loading.search ? "Previewing..." : `${adminSearchState?.total ?? 0} hits`}
                </span>
              </div>
              <p className="service-note">Route: POST /api/v1/admin/retrieval/search-preview</p>
              <p className="service-note">Rewritten Query</p>
              <pre>
                {adminSearchState?.rewrittenQuery ??
                  "Run preview search to validate the canonical admin retrieval preview route."}
              </pre>
              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Knowledge Base</th>
                      <th>Source Type</th>
                      <th>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminSearchState?.items.length ? (
                      adminSearchState.items.map((item) => (
                        <tr key={item.chunkId}>
                          <td>
                            <strong>{item.title}</strong>
                            <div className="table-note">{item.contentPreview}</div>
                            <div className="badge-list">
                              {item.tags.map((tag) => (
                                <span className="badge badge-secondary" key={`${item.chunkId}-${tag}`}>
                                  {tag}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td>{item.kbId ?? "-"}</td>
                          <td>{item.sourceType ?? "-"}</td>
                          <td>{item.score.toFixed(2)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={4} className="empty-cell">
                          No canonical admin search preview yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="result-box">
              <div className="section-header compact">
                <div>
                  <div className="eyebrow">Diagnostic Response</div>
                  <h2>Rewrite + Filters</h2>
                </div>
                {retrievalState ? <span className="pill">{retrievalState.strategy}</span> : null}
              </div>
              <p className="service-note">Route: POST /api/rag/v1/diagnose</p>
              <p className="service-note">Rewritten Query</p>
              <pre>{retrievalState?.rewrittenQuery ?? "Run diagnostics to inspect the rewrite plan."}</pre>
              <div className="inline-stat-row">
                <span className="service-note">Candidates: {retrievalState?.candidateCount ?? 0}</span>
                <span className="service-note">Top K: {retrievalState?.requestedTopK ?? 5}</span>
              </div>
              <p className="service-note">Query Terms</p>
              <div className="badge-list">
                {retrievalState?.queryTerms.length ? (
                  retrievalState.queryTerms.map((term) => (
                    <span className="badge" key={term}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">Query terms appear after diagnostics run.</span>
                )}
              </div>
              <p className="service-note">Expanded Terms</p>
              <div className="badge-list">
                {retrievalState?.expandedTerms.length ? (
                  retrievalState.expandedTerms.map((term) => (
                    <span className="badge badge-secondary" key={term}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">No synonym expansion yet.</span>
                )}
              </div>
              <p className="service-note">Applied Filters</p>
              <pre>
                {retrievalState
                  ? JSON.stringify(retrievalState.appliedFilters, null, 2)
                  : "Diagnostics will show source and tag filters here."}
              </pre>
              <p className="service-note">Unmatched Terms</p>
              <div className="badge-list">
                {retrievalState?.unmatchedTerms.length ? (
                  retrievalState.unmatchedTerms.map((term) => (
                    <span className="badge warning-pill" key={term}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">No unmatched terms detected yet.</span>
                )}
              </div>
              <p className="service-note">Source coverage</p>
              <div className="overview-source-list">
                {retrievalState?.sourceBreakdown.length ? (
                  retrievalState.sourceBreakdown.map((source) => (
                    <article className="overview-source-card" key={source.sourceId}>
                      <strong>{source.sourceName}</strong>
                      <span>{source.hitCount} hits</span>
                      <span>Best score {source.bestScore.toFixed(2)}</span>
                    </article>
                  ))
                ) : (
                  <span className="empty-cell">Source coverage appears here after diagnostics.</span>
                )}
              </div>
              <p className="service-note">Tag coverage</p>
              <div className="badge-list">
                {retrievalState?.tagBreakdown.length ? (
                  retrievalState.tagBreakdown.map((bucket) => (
                    <span className="badge badge-secondary" key={bucket.label}>
                      {bucket.label} · {bucket.count}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">Tag overlap appears here after diagnostics.</span>
                )}
              </div>
            </section>
            <section className="result-box">
              <div className="section-header compact">
                <div>
                  <div className="eyebrow">Canonical Admin Route</div>
                  <h2>Admin Retrieval Diagnostic</h2>
                </div>
                {adminDiagnosticState ? (
                  <span className={`pill ${adminDiagnosticState.coverage.degraded ? "warning-pill" : ""}`}>
                    {adminDiagnosticState.answerable ? "answerable" : "needs review"}
                  </span>
                ) : null}
              </div>
              <p className="service-note">Route: POST /api/v1/admin/retrieval/diagnostics</p>
              <p className="service-note">Rewritten Query</p>
              <pre>
                {adminDiagnosticState?.rewrittenQuery ??
                  "Run diagnostics to validate the canonical admin retrieval route."}
              </pre>
              <div className="inline-stat-row">
                <span className="service-note">
                  Candidates: {adminDiagnosticState?.coverage.candidateCount ?? 0}
                </span>
                <span className="service-note">
                  Degraded: {adminDiagnosticState?.coverage.degraded ? "yes" : "no"}
                </span>
              </div>
              <p className="service-note">Admin query terms</p>
              <div className="badge-list">
                {adminDiagnosticState?.debug.queryTerms.length ? (
                  adminDiagnosticState.debug.queryTerms.map((term) => (
                    <span className="badge" key={`admin-query-${term}`}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">Admin query terms appear after diagnostics run.</span>
                )}
              </div>
              <p className="service-note">Admin expanded terms</p>
              <div className="badge-list">
                {adminDiagnosticState?.debug.expandedTerms.length ? (
                  adminDiagnosticState.debug.expandedTerms.map((term) => (
                    <span className="badge badge-secondary" key={`admin-expanded-${term}`}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">No canonical admin expansion yet.</span>
                )}
              </div>
              <p className="service-note">Admin unmatched terms</p>
              <div className="badge-list">
                {adminDiagnosticState?.coverage.unmatchedTerms.length ? (
                  adminDiagnosticState.coverage.unmatchedTerms.map((term) => (
                    <span className="badge warning-pill" key={`admin-unmatched-${term}`}>
                      {term}
                    </span>
                  ))
                ) : (
                  <span className="empty-cell">No unmatched admin terms detected yet.</span>
                )}
              </div>
              {adminDiagnosticState?.notes.length ? (
                <ul className="coverage-list">
                  {adminDiagnosticState.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
              <div className="table-shell">
                <table>
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Knowledge Base</th>
                      <th>Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adminDiagnosticState?.sources.length ? (
                      adminDiagnosticState.sources.map((source) => (
                        <tr key={source.chunkId}>
                          <td>
                            <strong>{source.title}</strong>
                            <div className="table-note">{source.contentPreview}</div>
                          </td>
                          <td>{source.kbId ?? "-"}</td>
                          <td>{source.score.toFixed(2)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3} className="empty-cell">
                          No canonical admin retrieval diagnostic yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="result-box">
              <div className="eyebrow">Answer Preview</div>
              <pre>{answerState?.answer ?? "Run answer composition to preview grounded output."}</pre>
            </section>
            <CitationList
              citations={retrievalState?.citations ?? []}
              coverageNotes={retrievalState?.coverageNotes ?? []}
              degraded={retrievalState?.degraded ?? false}
            />
          </div>
        </section>
      </section>

      <section className="grid two-up">
        <SourceTable
          sources={knowledgeBases}
          selectedKnowledgeBaseId={selectedKnowledgeBaseId}
          onSelect={setSelectedKnowledgeBaseId}
        />
        <KnowledgeBaseSettingsPanel
          knowledgeBase={selectedKnowledgeBase}
          form={knowledgeBaseSettingsForm}
          loading={loading.updateKnowledgeBase}
          onChange={(patch) =>
            setKnowledgeBaseSettingsForm((current) => ({
              ...current,
              ...patch,
            }))
          }
          onSubmit={() => void handleUpdateKnowledgeBase()}
        />
      </section>

      <section className="grid">
        <DocumentTable
          documents={documents}
          sources={knowledgeBases}
          selectedDocumentId={selectedDocumentId}
          onSelect={setSelectedDocumentId}
        />
      </section>

      <section className="grid">
        <section className="grid two-up">
          <DocumentDetailPanel
            detail={selectedDocumentDetail}
            latestJob={selectedDocumentJob}
            loading={loading.documentDetail}
            jobLoading={loading.documentJob}
            confirmToken={confirmToken}
            onConfirmTokenChange={setConfirmToken}
            onReindex={() => void handleReindexDocument()}
            reindexLoading={loading.reindex}
          />
          <ChunkTable chunks={chunks} selectedDocument={selectedDocument} loading={loading.chunks} />
        </section>
      </section>

      <section className="grid two-up">
        <ActivityFeed ingestions={ingestions} sources={sources} documents={rawDocuments} />
        <AdminAuditPanel
          records={auditRecords}
          loading={loading.audit}
          resourceType={auditResourceType}
          action={auditAction}
          operatorId={auditOperatorId}
          onResourceTypeChange={setAuditResourceType}
          onActionChange={setAuditAction}
          onOperatorIdChange={setAuditOperatorId}
        />
      </section>
    </main>
  );
}
