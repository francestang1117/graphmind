import { Check, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { useDiseaseConceptSearch } from "../../hooks/useDiseaseProfiles";
import type { UnassignedDiseaseDocument } from "../../services/api";

interface Props {
  document: UnassignedDiseaseDocument;
  busy: boolean;
  onLink: (input: { documentId: string; conceptId: string; matchedAlias: string }) => void;
}

export default function DiseaseConceptPicker({ document, busy, onLink }: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<{ conceptId: string; alias: string } | null>(null);
  const results = useDiseaseConceptSearch(query);
  return (
    <div className="disease-concept-picker">
      <div className="disease-concept-search">
        <Search size={15} />
        <input
          value={query}
          onChange={(event) => { setQuery(event.target.value); setSelected(null); }}
          placeholder="Search the local disease dictionary"
          aria-label={`Search disease for ${document.title}`}
        />
      </div>
      {results.isLoading && <span className="disease-picker-hint">Searching locally...</span>}
      {!!query.trim() && !results.isLoading && !results.data?.items.length && (
        <span className="disease-picker-hint">No local concept found. Nothing is sent externally.</span>
      )}
      {results.data?.items.map((item) => (
        <button
          type="button"
          key={item.concept_id}
          className={`disease-concept-option ${selected?.conceptId === item.concept_id ? "selected" : ""}`}
          onClick={() => setSelected({ conceptId: item.concept_id, alias: item.matched_alias })}
        >
          <span><strong>{item.preferred_name_zh || item.preferred_name_en}</strong><small>{item.preferred_name_en} · matched "{item.matched_alias}"</small></span>
          {selected?.conceptId === item.concept_id && <Check size={15} />}
        </button>
      ))}
      {selected && (
        <button
          type="button"
          className="disease-link-button"
          disabled={busy}
          onClick={() => onLink({ documentId: document.document_id, conceptId: selected.conceptId, matchedAlias: selected.alias })}
        >
          {busy ? <Loader2 className="spin" size={14} /> : <Check size={14} />}
          Link to profile
        </button>
      )}
    </div>
  );
}
