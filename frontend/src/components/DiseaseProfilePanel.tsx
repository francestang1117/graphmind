import axios from "axios";
import {
  AlertCircle,
  BookOpen,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  useDiseaseComparisonPreview,
  useDiseaseProfileExternalSourceDocuments,
  useDiseaseProfileItems,
  useDiseaseProfiles,
} from "../hooks/useDiseaseProfiles";
import type {
  ComparisonLanguage,
  ComparisonPreview,
  DiseaseProfileDocument,
  DiseaseProfileItem,
  DiseaseProfileSection as SectionName,
} from "../services/api";
import DiseaseProfileHeader from "./disease-profile/DiseaseProfileHeader";
import DiseaseProfileList from "./disease-profile/DiseaseProfileList";
import DiseaseProfileSection from "./disease-profile/DiseaseProfileSection";
import DiseaseProfileStats from "./disease-profile/DiseaseProfileStats";
import DiseaseComparisonPanel from "./disease-profile/DiseaseComparisonPanel";
import { getComparisonMessages } from "./disease-profile/comparisonMessages";
import DiseaseSourceDrawer from "./disease-profile/DiseaseSourceDrawer";
import UnassignedDocuments from "./disease-profile/UnassignedDocuments";

interface Props {
  workspaceId: string | null;
  onOpenVisitPrep: () => void;
}

type ComparisonSourceSnapshot = {
  document_id: string;
  parsed_source_hash: string;
  analysis_run_id: string;
};

type ComparisonSnapshot = {
  contextToken: object;
  workspaceId: string | null;
  conceptId: string | null;
  language: ComparisonLanguage;
  sources: ComparisonSourceSnapshot[];
};

function snapshotsMatch(left: ComparisonSnapshot, right: ComparisonSnapshot) {
  return left.contextToken === right.contextToken
    && left.workspaceId === right.workspaceId
    && left.conceptId === right.conceptId
    && left.language === right.language
    && JSON.stringify(left.sources) === JSON.stringify(right.sources);
}

const SECTION_ORDER: SectionName[] = [
  "key_findings",
  "study_methods",
  "limitations",
  "what_it_means",
  "what_it_does_not_mean",
  "applicability",
  "future_research",
  "medical_terms",
  "clinician_questions",
  "external_studies",
];

function errorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 404) return "This source is no longer in the selected research project.";
    if (error.response?.status === 409) {
      if (error.response.data?.code === "disease_link_primary_exists") {
        return "Each document has one primary disease. Remove its current link before assigning another.";
      }
      if (
        error.response.data?.code === "comparison_source_changed"
        || error.response.data?.code === "comparison_report_invalid"
      ) {
        return "A selected source changed. Refresh the profile and select current documents again.";
      }
      return "This profile changed elsewhere. Refresh and try again.";
    }
    if (error.response?.status === 422) {
      if (error.response.data?.code === "comparison_invalid_selection") {
        return "Select two to five current documents with validated analyses.";
      }
      return "The selected comparison sources are not valid.";
    }
    if (error.response?.status === 503) return "Disease profile storage is temporarily unavailable.";
  }
  return fallback;
}

export default function DiseaseProfilePanel({ workspaceId, onOpenVisitPrep }: Props) {
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null);
  const [expandedSection, setExpandedSection] = useState<SectionName | null>(null);
  const [sectionCursors, setSectionCursors] = useState<Partial<Record<SectionName, string | null>>>({});
  const [extraItems, setExtraItems] = useState<Partial<Record<SectionName, DiseaseProfileItem[]>>>({});
  const [completedSections, setCompletedSections] = useState<Partial<Record<SectionName, boolean>>>({});
  const [sourceItem, setSourceItem] = useState<DiseaseProfileItem | null>(null);
  const [actionError, setActionError] = useState("");
  const [needsProfileRefresh, setNeedsProfileRefresh] = useState(false);
  const [refreshingProfile, setRefreshingProfile] = useState(false);
  const [documentSelection, setDocumentSelection] = useState<{ contextKey: string; ids: string[] }>({
    contextKey: "",
    ids: [],
  });
  const [comparisonResult, setComparisonResult] = useState<{
    snapshot: ComparisonSnapshot;
    preview: ComparisonPreview;
  } | null>(null);
  const [comparisonLanguage, setComparisonLanguage] = useState<ComparisonLanguage>("en");
  const comparisonMessages = getComparisonMessages(comparisonLanguage);
  const profiles = useDiseaseProfiles(workspaceId, selectedConceptId);
  const effectiveConceptId = profiles.selectedConceptId;
  const comparisonMutation = useDiseaseComparisonPreview(workspaceId, effectiveConceptId);
  const comparisonContextKey = `${workspaceId ?? "none"}:${effectiveConceptId ?? "none"}`;
  const comparisonContextToken = useMemo(
    () => ({ contextKey: comparisonContextKey }),
    [comparisonContextKey],
  );
  const comparisonRequestVersion = useRef(0);
  const currentComparisonSnapshotRef = useRef<ComparisonSnapshot | null>(null);
  const rawSelectedDocumentIds = useMemo(
    () => documentSelection.contextKey === comparisonContextKey ? documentSelection.ids : [],
    [comparisonContextKey, documentSelection.contextKey, documentSelection.ids],
  );
  const activeSection = expandedSection ?? "key_findings";
  const sectionItemsQuery = useDiseaseProfileItems(
    workspaceId,
    effectiveConceptId,
    activeSection,
    sectionCursors[activeSection] ?? null,
    Boolean(expandedSection),
  );
  const externalDocumentsQuery = useDiseaseProfileExternalSourceDocuments(
    workspaceId,
    effectiveConceptId,
    sourceItem,
  );

  const selectedProfile = profiles.detail;
  const selectedProfileSectionMap = useMemo(
    () => new Map((selectedProfile?.sections ?? []).map((section) => [section.section, section])),
    [selectedProfile?.sections],
  );
  const linkedDocuments = useMemo(
    () => profiles.linkedDocuments ?? selectedProfile?.documents ?? [],
    [profiles.linkedDocuments, selectedProfile?.documents],
  );
  const selectedDocumentIds = useMemo(
    () => rawSelectedDocumentIds.filter((documentId) => {
      const document = linkedDocuments.find((item) => item.document_id === documentId);
      return Boolean(
        document?.source_status === "current"
        && document.parsed_source_hash
        && document.current_analysis_run_id,
      );
    }),
    [linkedDocuments, rawSelectedDocumentIds],
  );
  const documentsQuery = profiles.documentsQuery;
  const currentComparisonSnapshot = useMemo<ComparisonSnapshot>(() => ({
    contextToken: comparisonContextToken,
    workspaceId,
    conceptId: effectiveConceptId,
    language: comparisonLanguage,
    sources: selectedDocumentIds.map((documentId) => ({
      document_id: documentId,
      parsed_source_hash: linkedDocuments.find((document) => document.document_id === documentId)?.parsed_source_hash ?? "",
      analysis_run_id: linkedDocuments.find((document) => document.document_id === documentId)?.current_analysis_run_id ?? "",
    })),
  }), [
    comparisonContextToken,
    workspaceId,
    effectiveConceptId,
    comparisonLanguage,
    selectedDocumentIds,
    linkedDocuments,
  ]);
  useLayoutEffect(() => {
    currentComparisonSnapshotRef.current = currentComparisonSnapshot;
  }, [currentComparisonSnapshot]);

  const invalidateComparison = () => {
    comparisonRequestVersion.current += 1;
    setComparisonResult(null);
    comparisonMutation.reset();
  };

  const toggleSection = (section: SectionName) => {
    setActionError("");
    setExpandedSection((current) => current === section ? null : section);
    if (expandedSection !== section) {
      setSectionCursors((current) => ({ ...current, [section]: null }));
      setExtraItems((current) => ({ ...current, [section]: [] }));
      setCompletedSections((current) => ({ ...current, [section]: false }));
    }
  };

  const selectConcept = (conceptId: string) => {
    invalidateComparison();
    setSelectedConceptId(conceptId);
    setExpandedSection(null);
    setSectionCursors({});
    setExtraItems({});
    setCompletedSections({});
    setSourceItem(null);
    setDocumentSelection({ contextKey: "", ids: [] });
    setActionError("");
    setNeedsProfileRefresh(false);
  };

  const toggleDocumentSelection = (documentId: string) => {
    setActionError("");
    invalidateComparison();
    setDocumentSelection((current) => {
      const selected = current.contextKey === comparisonContextKey ? selectedDocumentIds : [];
      return {
        contextKey: comparisonContextKey,
        ids: selected.includes(documentId)
          ? selected.filter((value) => value !== documentId)
          : selected.length < 5 ? [...selected, documentId] : selected,
      };
    });
  };

  const linkDocument = async (input: { documentId: string; conceptId: string; matchedAlias: string }) => {
    setActionError("");
    try {
      await profiles.linkDocument(input);
      selectConcept(input.conceptId);
    } catch (error) {
      setActionError(errorMessage(error, "Could not link this document."));
    }
  };

  const unlinkDocument = async (documentId: string) => {
    if (!effectiveConceptId) return;
    setActionError("");
    invalidateComparison();
    try {
      await profiles.unlinkDocument({ documentId, conceptId: effectiveConceptId });
      setDocumentSelection((current) => ({
        contextKey: current.contextKey,
        ids: current.ids.filter((value) => value !== documentId),
      }));
    } catch (error) {
      setActionError(errorMessage(error, "Could not remove this document from the profile."));
    }
  };

  const compareSelectedDocuments = async () => {
    const selectedDocuments = selectedDocumentIds.map((documentId) =>
      linkedDocuments.find((document) => document.document_id === documentId));
    if (selectedDocuments.length !== selectedDocumentIds.length) {
      setActionError("A selected source is no longer available. Refresh the profile and select documents again.");
      invalidateComparison();
      return;
    }
    const currentDocuments = selectedDocuments.filter((document): document is DiseaseProfileDocument => Boolean(
      document?.source_status === "current"
      && document.parsed_source_hash
      && document.current_analysis_run_id,
    ));
    if (currentDocuments.length !== selectedDocumentIds.length || currentDocuments.length < 2 || !effectiveConceptId || !workspaceId) {
      setActionError("Select two to five current documents with validated analyses.");
      return;
    }
    const snapshot: ComparisonSnapshot = {
      ...currentComparisonSnapshot,
      sources: currentDocuments.map((document) => ({
        document_id: document.document_id,
        parsed_source_hash: document.parsed_source_hash,
        analysis_run_id: document.current_analysis_run_id as string,
      })),
    };
    const requestVersion = ++comparisonRequestVersion.current;
    setActionError("");
    setComparisonResult(null);
    try {
      const preview = await comparisonMutation.mutateAsync({
        documents: currentDocuments.map((document) => ({
          document_id: document.document_id,
          expected_parsed_source_hash: document.parsed_source_hash,
          expected_analysis_run_id: document.current_analysis_run_id as string,
        })),
        language: comparisonLanguage,
      });
      const current = currentComparisonSnapshotRef.current;
      if (requestVersion !== comparisonRequestVersion.current || !current || !snapshotsMatch(snapshot, current)) return;
      setComparisonResult({ snapshot, preview });
    } catch (error) {
      const current = currentComparisonSnapshotRef.current;
      if (requestVersion !== comparisonRequestVersion.current || !current || !snapshotsMatch(snapshot, current)) return;
      const code = axios.isAxiosError(error) ? error.response?.data?.code : undefined;
      if (code === "comparison_source_changed" || code === "comparison_report_invalid") {
        setComparisonResult(null);
        setActionError("");
        setNeedsProfileRefresh(true);
        return;
      }
      setActionError(errorMessage(error, "Could not build this comparison preview."));
    }
  };

  const refreshProfile = async () => {
    const selectedBeforeRefresh = selectedDocumentIds;
    setRefreshingProfile(true);
    setActionError("");
    invalidateComparison();
    try {
      const refreshedProfile = await profiles.refreshCurrentProfile();
      const refreshedDocuments = refreshedProfile?.documents ?? [];
      const refreshedById = new Map(
        [...linkedDocuments, ...refreshedDocuments].map((document) => [document.document_id, document]),
      );
      const removedIds = selectedBeforeRefresh.filter((documentId) => {
        const document = refreshedById.get(documentId);
        return !document
          || document.source_status !== "current"
          || !document.parsed_source_hash
          || !document.current_analysis_run_id;
      });
      if (removedIds.length > 0) {
        setDocumentSelection((current) => ({
          contextKey: current.contextKey,
          ids: current.ids.filter((documentId) => !removedIds.includes(documentId)),
        }));
        setActionError(comparisonMessages.partialSourcesUnavailable);
      }
      setNeedsProfileRefresh(false);
    } catch (error) {
      setActionError(errorMessage(error, "Could not refresh the disease profile."));
    } finally {
      setRefreshingProfile(false);
    }
  };

  const loadMore = () => {
    const pageItems = sectionItemsQuery.data?.items ?? [];
    if (!pageItems.length) {
      setCompletedSections((current) => ({ ...current, [activeSection]: true }));
      return;
    }
    setExtraItems((current) => {
      const previous = current[activeSection] ?? [];
      const seen = new Set(previous.map((item) => item.id));
      return {
        ...current,
        [activeSection]: [...previous, ...pageItems.filter((item) => !seen.has(item.id))],
      };
    });
    const next = sectionItemsQuery.data?.next_cursor;
    if (next) {
      setSectionCursors((current) => ({ ...current, [activeSection]: next }));
    } else {
      setCompletedSections((current) => ({ ...current, [activeSection]: true }));
    }
  };

  if (!workspaceId) {
    return (
      <div className="disease-profile-empty-page">
        <BookOpen size={32} />
        <h2>Select a research project</h2>
        <p>Disease profiles are kept inside their research project.</p>
      </div>
    );
  }

  const loadError = profiles.listQuery.error
    || profiles.unassignedQuery.error
    || documentsQuery?.error;
  const relatedDocuments = Array.from(
    new Map(
      (externalDocumentsQuery.data?.pages.flatMap((page) => page.items) ?? [])
        .map((document) => [document.document_id, document]),
    ).values(),
  );
  return (
    <div className="disease-profiles-panel">
      <aside className="disease-profiles-sidebar">
        <div className="disease-profile-sidebar-heading">
          <div><span className="disease-profile-eyebrow">Current project</span><h2>Disease profiles</h2></div>
          <BookOpen size={22} />
        </div>
        <DiseaseProfileList
          profiles={profiles.list}
          selectedId={effectiveConceptId}
          loading={profiles.listQuery.isLoading}
          onSelect={selectConcept}
          hasMore={profiles.hasMoreProfiles}
          loadingMore={profiles.loadingMoreProfiles}
          onLoadMore={() => { void profiles.loadMoreProfiles(); }}
        />
        <UnassignedDocuments
          documents={profiles.unassigned}
          total={profiles.unassignedTotal ?? profiles.unassigned.length}
          loading={profiles.unassignedQuery.isLoading}
          loadingMore={profiles.loadingMoreUnassigned}
          hasMore={profiles.hasMoreUnassigned}
          error={profiles.unassignedQuery.error}
          linking={profiles.linking}
          onLink={linkDocument}
          onLoadMore={() => { void profiles.loadMoreUnassigned?.(); }}
          onRetry={() => { void profiles.unassignedQuery.refetch(); }}
        />
      </aside>

      <main className="disease-profiles-main">
        <div className="disease-profile-safety-notice">
          <ShieldAlert size={17} />
          <span>This page organizes research-project sources. It does not provide diagnosis, treatment advice, or individualized medical opinions.</span>
        </div>
        {loadError && (
          <div className="disease-profile-inline-error" role="alert">
            <AlertCircle size={16} />
            <span>Could not load all disease profile data.</span>
            <button type="button" onClick={() => { void profiles.listQuery.refetch(); void profiles.unassignedQuery.refetch(); void profiles.detailQuery.refetch(); void documentsQuery?.refetch(); }}>
              <RefreshCw size={14} /> Retry
            </button>
          </div>
        )}
        {needsProfileRefresh && (
          <div className="disease-profile-inline-error" role="alert">
            <AlertCircle size={16} />
            <span>{comparisonMessages.sourceChanged}</span>
            <button
              type="button"
              onClick={() => { void refreshProfile(); }}
              disabled={refreshingProfile}
            >
              <RefreshCw size={14} />
              {refreshingProfile ? comparisonMessages.refreshingProfile : comparisonMessages.refreshProfile}
            </button>
          </div>
        )}
        {actionError && <div className="disease-profile-inline-error" role="alert"><AlertCircle size={16} /><span>{actionError}</span></div>}
        {!effectiveConceptId && !profiles.listQuery.isLoading ? (
          <div className="disease-profile-empty-page compact">
            <BookOpen size={28} />
            <h2>No disease profile selected</h2>
            <p>Link a classified medical document to a local disease concept to begin.</p>
          </div>
        ) : profiles.detailQuery.isLoading ? (
          <div className="disease-profile-loading"><Loader2 className="spin" size={20} /> Loading profile sources...</div>
        ) : selectedProfile ? (
          <>
            <DiseaseProfileHeader profile={selectedProfile} onOpenVisitPrep={onOpenVisitPrep} />
            {selectedProfile.warnings.map((warning) => <div className="disease-profile-warning" key={warning}><AlertCircle size={14} /> {warning}</div>)}
            <DiseaseProfileStats stats={selectedProfile.stats} />
            <section className="disease-profile-documents">
              <div className="disease-profile-subheading"><div><span className="disease-profile-eyebrow">Linked sources</span><h2>{selectedProfile.document_count} documents in this profile</h2></div></div>
              <p className="disease-profile-document-policy">Each document has one primary disease. Remove the current link to return it to Needs review before assigning another disease.</p>
              <div className="disease-profile-comparison-toolbar">
                <div>
                  <span className="disease-profile-eyebrow">{comparisonMessages.compareEyebrow}</span>
                  <strong>{comparisonMessages.selectedCount(selectedDocumentIds.length)}</strong>
                </div>
                <label>
                  {comparisonMessages.languageLabel}
                  <select
                    value={comparisonLanguage}
                    onChange={(event) => {
                      invalidateComparison();
                      setActionError("");
                      setComparisonLanguage(event.target.value as ComparisonLanguage);
                    }}
                  >
                    <option value="en">English</option>
                    <option value="zh">中文</option>
                    <option value="ja">日本語</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="disease-profile-compare-button"
                  onClick={() => { void compareSelectedDocuments(); }}
                  disabled={selectedDocumentIds.length < 2 || comparisonMutation.isPending}
                >
                  {comparisonMutation.isPending ? comparisonMessages.comparing : comparisonMessages.compare}
                </button>
              </div>
              <div className="disease-profile-document-list">
                {linkedDocuments.map((document) => (
                  <div className="disease-profile-document-row" key={document.document_id}>
                    <div className="disease-profile-document-select">
                      <input
                        type="checkbox"
                        aria-label={`Select ${document.title} for comparison`}
                        checked={selectedDocumentIds.includes(document.document_id)}
                        onChange={() => toggleDocumentSelection(document.document_id)}
                        disabled={document.source_status !== "current"
                          || !document.parsed_source_hash
                          || !document.current_analysis_run_id
                          || (!selectedDocumentIds.includes(document.document_id) && selectedDocumentIds.length >= 5)}
                      />
                      <div>
                        <strong>{document.title}</strong>
                        <span>{document.document_kind} · {document.source_status}{document.document_date ? ` · ${document.document_date}` : ""}</span>
                      </div>
                    </div>
                    <button type="button" className="disease-icon-button" aria-label={`Remove ${document.title} from profile`} title="Remove document from profile" onClick={() => { void unlinkDocument(document.document_id); }} disabled={profiles.unlinking}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
              {documentsQuery?.error && (
                <div className="disease-profile-inline-error" role="alert">
                  <AlertCircle size={14} />
                  <span>Could not load more linked documents.</span>
                  <button type="button" onClick={() => { void documentsQuery?.refetch(); }}>
                    <RefreshCw size={14} /> Retry
                  </button>
                </div>
              )}
              {profiles.hasMoreDocuments && (
                <button
                  type="button"
                  className="disease-profile-load-more"
                  onClick={() => { void profiles.loadMoreDocuments?.(); }}
                  disabled={profiles.loadingMoreDocuments}
                >
                  {profiles.loadingMoreDocuments ? "Loading..." : "Load more linked documents"}
                </button>
              )}
            </section>
            {comparisonResult?.preview
              && snapshotsMatch(comparisonResult.snapshot, currentComparisonSnapshot) && (
              <DiseaseComparisonPanel
                preview={comparisonResult.preview}
                workspaceId={workspaceId}
                language={comparisonLanguage}
              />
            )}
            <div className="disease-profile-sections">
              {SECTION_ORDER.map((section) => {
                const summary = selectedProfileSectionMap.get(section);
                const loaded = extraItems[section] ?? [];
                const preview = summary?.items ?? [];
                const seen = new Set(preview.map((item) => item.id));
                const items = [...preview, ...loaded.filter((item) => !seen.has(item.id))];
                const page = expandedSection === section ? sectionItemsQuery.data : undefined;
                const hasMore = !completedSections[section]
                  && (Boolean(page?.next_cursor) || items.length < (summary?.count ?? 0));
                return (
                  <DiseaseProfileSection
                    key={section}
                    name={section}
                    count={summary?.count ?? 0}
                    items={items}
                    expanded={expandedSection === section}
                    loading={expandedSection === section && sectionItemsQuery.isLoading}
                    hasMore={hasMore}
                    truncated={Boolean(page?.truncated)}
                    onToggle={() => toggleSection(section)}
                    onLoadMore={loadMore}
                    onOpenSource={setSourceItem}
                  />
                );
              })}
            </div>
          </>
        ) : (
          <div className="disease-profile-empty-page compact"><BookOpen size={28} /><h2>Profile not available</h2><p>The profile may have changed or been removed.</p></div>
        )}
      </main>
      {sourceItem && (
        <DiseaseSourceDrawer
          item={sourceItem}
          onClose={() => setSourceItem(null)}
          relatedDocuments={relatedDocuments}
          relatedDocumentsLoading={externalDocumentsQuery.isLoading}
          relatedDocumentsError={externalDocumentsQuery.error}
          relatedDocumentsHasMore={Boolean(externalDocumentsQuery.hasNextPage)}
          relatedDocumentsLoadingMore={externalDocumentsQuery.isFetchingNextPage}
          onLoadMoreRelatedDocuments={() => { void externalDocumentsQuery.fetchNextPage(); }}
          onRetryRelatedDocuments={() => { void externalDocumentsQuery.refetch(); }}
        />
      )}
    </div>
  );
}
