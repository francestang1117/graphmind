import axios from "axios";
import {
  AlertCircle,
  BookOpen,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import {
  useDiseaseProfileItems,
  useDiseaseProfiles,
} from "../hooks/useDiseaseProfiles";
import type {
  DiseaseProfileItem,
  DiseaseProfileSection as SectionName,
} from "../services/api";
import DiseaseProfileHeader from "./disease-profile/DiseaseProfileHeader";
import DiseaseProfileList from "./disease-profile/DiseaseProfileList";
import DiseaseProfileSection from "./disease-profile/DiseaseProfileSection";
import DiseaseProfileStats from "./disease-profile/DiseaseProfileStats";
import DiseaseSourceDrawer from "./disease-profile/DiseaseSourceDrawer";
import UnassignedDocuments from "./disease-profile/UnassignedDocuments";

interface Props {
  workspaceId: string | null;
  onOpenVisitPrep: () => void;
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
      return "This profile changed elsewhere. Refresh and try again.";
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
  const [sourceItem, setSourceItem] = useState<DiseaseProfileItem | null>(null);
  const [actionError, setActionError] = useState("");
  const profiles = useDiseaseProfiles(workspaceId, selectedConceptId);
  const effectiveConceptId = profiles.selectedConceptId;
  const activeSection = expandedSection ?? "key_findings";
  const sectionItemsQuery = useDiseaseProfileItems(
    workspaceId,
    effectiveConceptId,
    activeSection,
    sectionCursors[activeSection] ?? null,
    Boolean(expandedSection),
  );

  const selectedProfile = profiles.detail;
  const selectedProfileSectionMap = useMemo(
    () => new Map((selectedProfile?.sections ?? []).map((section) => [section.section, section])),
    [selectedProfile?.sections],
  );

  const toggleSection = (section: SectionName) => {
    setActionError("");
    setExpandedSection((current) => current === section ? null : section);
    if (expandedSection !== section) {
      setSectionCursors((current) => ({ ...current, [section]: null }));
      setExtraItems((current) => ({ ...current, [section]: [] }));
    }
  };

  const selectConcept = (conceptId: string) => {
    setSelectedConceptId(conceptId);
    setExpandedSection(null);
    setSectionCursors({});
    setExtraItems({});
    setSourceItem(null);
    setActionError("");
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
    try {
      await profiles.unlinkDocument({ documentId, conceptId: effectiveConceptId });
    } catch (error) {
      setActionError(errorMessage(error, "Could not remove this document from the profile."));
    }
  };

  const loadMore = () => {
    const next = sectionItemsQuery.data?.next_cursor;
    if (!next) return;
    const pageItems = sectionItemsQuery.data?.items ?? [];
    setExtraItems((current) => {
      const previous = current[activeSection] ?? [];
      const seen = new Set(previous.map((item) => item.id));
      return {
        ...current,
        [activeSection]: [...previous, ...pageItems.filter((item) => !seen.has(item.id))],
      };
    });
    setSectionCursors((current) => ({ ...current, [activeSection]: next }));
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

  const loadError = profiles.listQuery.error || profiles.unassignedQuery.error;
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
        />
        <UnassignedDocuments
          documents={profiles.unassigned}
          loading={profiles.unassignedQuery.isLoading}
          linking={profiles.linking}
          onLink={linkDocument}
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
            <button type="button" onClick={() => { void profiles.listQuery.refetch(); void profiles.unassignedQuery.refetch(); void profiles.detailQuery.refetch(); }}>
              <RefreshCw size={14} /> Retry
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
              <div className="disease-profile-subheading"><div><span className="disease-profile-eyebrow">Linked sources</span><h2>{selectedProfile.documents.length} documents in this profile</h2></div></div>
              <p className="disease-profile-document-policy">Each document has one primary disease. Remove the current link to return it to Needs review before assigning another disease.</p>
              <div className="disease-profile-document-list">
                {selectedProfile.documents.map((document) => (
                  <div className="disease-profile-document-row" key={document.document_id}>
                    <div><strong>{document.title}</strong><span>{document.document_kind} · {document.source_status}{document.document_date ? ` · ${document.document_date}` : ""}</span></div>
                    <button type="button" className="disease-icon-button" aria-label={`Remove ${document.title} from profile`} title="Remove document from profile" onClick={() => { void unlinkDocument(document.document_id); }} disabled={profiles.unlinking}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </section>
            <div className="disease-profile-sections">
              {SECTION_ORDER.map((section) => {
                const summary = selectedProfileSectionMap.get(section);
                const loaded = extraItems[section] ?? [];
                const preview = summary?.items ?? [];
                const seen = new Set(preview.map((item) => item.id));
                const items = [...preview, ...loaded.filter((item) => !seen.has(item.id))];
                const hasMore = Boolean(sectionItemsQuery.data?.next_cursor) || items.length < (summary?.count ?? 0);
                return (
                  <DiseaseProfileSection
                    key={section}
                    name={section}
                    count={summary?.count ?? 0}
                    items={items}
                    expanded={expandedSection === section}
                    loading={expandedSection === section && sectionItemsQuery.isLoading}
                    hasMore={hasMore}
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
      {sourceItem && <DiseaseSourceDrawer item={sourceItem} onClose={() => setSourceItem(null)} />}
    </div>
  );
}
