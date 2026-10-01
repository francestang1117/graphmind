import type { ReactNode } from "react";
import type { DiseaseGuideTerm } from "../services/api";

interface MedicalTermProps {
  term: DiseaseGuideTerm;
  children?: ReactNode;
}

export default function MedicalTerm({ term, children }: MedicalTermProps) {
  return (
    <details className="disease-guide-term">
      <summary>{term.label}是什么意思？</summary>
      <div className="disease-guide-term-body">
        <p>{term.definition.text}</p>
        {term.context && <p>{term.context.text}</p>}
        {children}
      </div>
    </details>
  );
}
