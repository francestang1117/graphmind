import { CheckCircle2, CircleAlert } from "lucide-react";
import type { AmbiguousLiteratureConcept, LiteratureConceptSelection } from "../../../services/api";

interface Props {
  matches: AmbiguousLiteratureConcept[];
  selections: LiteratureConceptSelection[];
  onSelect: (matchId: string, conceptId: string) => void;
}

export default function DiseaseConceptPicker({ matches, selections, onSelect }: Props) {
  if (!matches.length) return null;

  return (
    <section className="literature-concept-picker" aria-labelledby="literature-concept-heading">
      <div className="literature-subheading" id="literature-concept-heading">
        <CircleAlert size={15} />
        <strong>Choose the disease concept</strong>
      </div>
      <p>Several local disease matches were found. Select the intended concept before anything is sent to PubMed.</p>
      <div className="literature-concept-groups">
        {matches.map((match) => {
          const selected = selections.find((selection) => selection.match_id === match.match_id)?.concept_id;
          return (
            <fieldset className="literature-concept-group" key={match.match_id}>
              <legend>Matched text: {match.matched_text}</legend>
              <div className="literature-candidate-list">
                {match.candidates.map((candidate) => (
                  <label className={`literature-candidate${selected === candidate.concept_id ? " selected" : ""}`} key={candidate.concept_id}>
                    <input
                      type="radio"
                      name={`concept-${match.match_id}`}
                      value={candidate.concept_id}
                      checked={selected === candidate.concept_id}
                      onChange={() => onSelect(match.match_id, candidate.concept_id)}
                    />
                    <span>
                      <strong>{candidate.display_name_zh || candidate.preferred_name}</strong>
                      <small>{candidate.preferred_name}{candidate.mesh_id ? ` · MeSH ${candidate.mesh_id}` : ""}</small>
                    </span>
                    {selected === candidate.concept_id && <CheckCircle2 size={15} />}
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}
      </div>
    </section>
  );
}
