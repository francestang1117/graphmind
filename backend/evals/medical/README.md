# Medical Evaluation Baseline

This directory contains the versioned, offline quality baseline for the
medical workflows. Version `v1` is deliberately small and deterministic so it
can run in CI without API keys, PubMed access, OpenAI calls, or other external
network dependencies.

## Scope

The current package covers five production boundaries:

- `terminology`: local disease normalization, ambiguity, privacy, and
  fail-closed external-query behavior
- `insight_safety`: citation presence, support-boundary rules, safety wording,
  and reference/preclinical/number checks
- `literature_matching`: deterministic candidate ranking, abstention,
  retraction exclusion, and study-type classification
- `clinician_questions`: server-owned question templates, source binding,
  evidence limits, and safe omission of unsupported suggestions
- `visit_preparation`: workspace-scoped question saving, source freshness,
  status/priority management, and immutable visit-brief snapshots
- `disease_profiles`: deterministic multi-document grouping, concept scope,
  source completeness, study-population separation, and retraction visibility

The package contains synthetic non-identifying text only. It is not a clinical
benchmark, diagnostic evaluation, evidence-quality assessment, or substitute
for clinician review. The observed ranking metrics are engineering signals and
have no medical interpretation. The original 35 cases and the
visit-preparation cases are engineering regression baselines, not
clinician-validated medical quality benchmarks; expert-reviewed cases should
be added incrementally.

## Package Contract

`manifest.json` is the entry point for one immutable dataset version. Each
manifest reference points to one strict `medical-eval-v1` case file. A case
declares:

- a stable ID, suite, language, tags, and review status;
- deterministic input and expected output;
- a short rationale and optional local fixtures;
- `gate_fields`, which are the only fields that can fail the CI gate;
- `source_references` and `last_reviewed` metadata.

The loader rejects unknown fields, unsupported schemas, duplicate IDs, paths
outside the package, missing fixtures, malformed cases, and common personal
identifiers. Keep patient names, record numbers, contact details, and real
clinical narratives out of this directory.

## Running Locally

From the project root:

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/run_medical_eval.py \
  --suite smoke --fail-on-gate

PYTHONPATH=backend .venv/bin/python backend/scripts/run_medical_eval.py \
  --suite full \
  --json-output /tmp/medical-eval.json \
  --markdown-output /tmp/medical-eval.md \
  --fail-on-gate
```

Exit code `0` means the selected hard gates passed. Exit code `1` means a hard
gate failed when `--fail-on-gate` was supplied. Exit code `2` means the dataset
or selection could not be loaded or validated. Empty selections and selections
without hard-gated fields fail closed. The Markdown report is safe for an Actions
summary and the JSON report is suitable for artifact comparison.

## Adding or Changing a Case

1. Add a strict case JSON under the suite directory and a local fixture only
   when the adapter needs one.
2. Add exactly one matching entry to `manifest.json` and update `case_count`.
3. Keep the case deterministic and declare only genuinely hard expectations in
   `gate_fields`.
4. Include a rationale, review status, language, and review date. Prefer
   synthetic text or public non-identifying excerpts.
5. Run the loader tests, runner tests, and the full CLI. Review both report
   formats for unexpected mismatches.
6. Bump `dataset_version` when changing the meaning of an existing case or its
   expected behavior. Do not silently rewrite expectations to hide a
   production regression.

The terminology adapter records run creation, queue, and provider-release
counts using an offline fake provider, but only after the shared confirmation
contract accepts the case inputs. The insight adapter replays cases through the
full medical insight analyzer, including its repair attempt, using an offline
fake provider; pipeline acceptance/rejection and provider call counts are hard
gates. The hard gates intentionally cover safety and provenance boundaries.
Precision, recall, MRR, abstention, and expected-behavior rates remain
observations until they have an explicit review-approved threshold and a
documented rationale.

The visit-preparation adapter exercises server-owned question binding,
idempotent refresh behavior, stale-source refusal, selection limits, dismissed
question handling, and immutable snapshot semantics without calling external
services. The disease-profile adapter expands compact synthetic records and
passes them through the production deterministic aggregator. It checks that
multiple documents stay separate, foreign concepts do not leak into a profile,
Orphanet identifiers remain stable, animal and in-vitro evidence stay distinct
from human studies, withdrawn articles remain visible with warnings, and no
overall confidence or treatment ranking is invented.

The `medical-eval-v1.3.0` package contains 50 synthetic cases. These are
engineering regression checks, not clinically expert-validated quality
judgments; expert review should be added incrementally.
