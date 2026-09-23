import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import MedicalInsightPanel from "../components/upload/MedicalInsightPanel";
import { ApplicationUpdateIncompleteError } from "../services/runtimeVersion";

const api = vi.hoisted(() => ({
  getCurrentMedicalInsights: vi.fn(),
  getMedicalInsightConfig: vi.fn(),
  getMedicalInsightRun: vi.fn(),
  startMedicalInsights: vi.fn(),
  reanalyzeMedicalInsights: vi.fn(),
}));

vi.mock("../services/api", () => api);
vi.mock("../hooks/useClinicianQuestions", () => ({
  useClinicianQuestions: () => ({
    saveQuestion: vi.fn(),
    savedSuggestionIds: new Set<string>(),
    staleSuggestionIds: new Set<string>(),
    savingSuggestionId: null,
    saveError: false,
  }),
}));
vi.mock("../components/upload/literature/LiteratureEvidencePanel", () => ({
  default: () => null,
}));

const currentRunRequest = Object.assign(new Error("analysis is outdated"), {
  isAxiosError: true,
  response: { status: 409, data: { code: "analysis_outdated" } },
});

const localConfig = {
  enabled: true,
  configured: true,
  provider: "extractive",
  model_name: "extractive-v3",
  external_processing: false,
  requires_confirmation: false,
  sends_selected_excerpts: false,
  redact_pii: true,
  config_fingerprint: "local-config-v2",
};

const externalConfig = {
  ...localConfig,
  provider: "openai",
  model_name: "gpt-test",
  external_processing: true,
  requires_confirmation: true,
  sends_selected_excerpts: true,
  config_fingerprint: "external-config-v2",
};

function queuedRun() {
  return {
    run_id: "run-new",
    document_id: "doc-1",
    workspace_id: "workspace-1",
    status: "queued",
    source_hash: "source-new",
    parsed_source_hash: "parsed-new",
    provider: "extractive",
    model_name: "extractive-v3",
    prompt_version: "medical-insights-v3+medical-insights-readable-v6",
    schema_version: "medical-insights-v3",
  };
}

function renderPanel() {
  return render(
    <MedicalInsightPanel
      documentId="doc-1"
      workspaceId="workspace-1"
      title="fabry-study.pdf"
      onClose={vi.fn()}
    />,
  );
}

describe("MedicalInsightPanel outdated analysis recovery", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("automatically replaces outdated local analysis without showing the old report", async () => {
    api.getCurrentMedicalInsights.mockRejectedValue(currentRunRequest);
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);
    api.startMedicalInsights.mockResolvedValue(queuedRun());

    renderPanel();

    await waitFor(() => expect(api.startMedicalInsights).toHaveBeenCalledWith(
      "doc-1",
      "workspace-1",
      false,
      "local-config-v2",
    ));
    expect(await screen.findByText("Waiting to analyze")).toBeInTheDocument();
    expect(screen.queryByText(/ary Gb3/)).not.toBeInTheDocument();
    expect(screen.queryByText("Objectives The study assessed a biomarker.")).not.toBeInTheDocument();
  });

  it("requires fresh confirmation before re-running an outdated external analysis", async () => {
    const user = userEvent.setup();
    api.getCurrentMedicalInsights.mockRejectedValue(currentRunRequest);
    api.getMedicalInsightConfig.mockResolvedValue(externalConfig);
    api.reanalyzeMedicalInsights.mockResolvedValue(queuedRun());

    renderPanel();

    expect(await screen.findByRole("dialog", { name: "Confirm external document processing" })).toBeInTheDocument();
    expect(api.startMedicalInsights).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm and analyze" }));

    await waitFor(() => expect(api.reanalyzeMedicalInsights).toHaveBeenCalledWith(
      "doc-1",
      "workspace-1",
      true,
      "external-config-v2",
    ));
  });

  it("hides a run that becomes outdated while the panel is polling it", async () => {
    api.getCurrentMedicalInsights.mockResolvedValue({
      ...queuedRun(),
      run_id: "run-old",
      status: "running",
    });
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);
    api.getMedicalInsightRun.mockResolvedValue({
      ...queuedRun(),
      run_id: "run-old",
      status: "succeeded",
      outdated: true,
      is_current: false,
      report: {
        key_findings: [{ statement: "LEGACY FINDING MUST STAY HIDDEN" }],
      },
    });
    api.startMedicalInsights.mockResolvedValue(queuedRun());

    renderPanel();

    expect(await screen.findByText("Analyzing document")).toBeInTheDocument();
    await waitFor(() => expect(api.startMedicalInsights).toHaveBeenCalledWith(
      "doc-1",
      "workspace-1",
      false,
      "local-config-v2",
    ), { timeout: 4000 });
    expect(screen.queryByText("LEGACY FINDING MUST STAY HIDDEN")).not.toBeInTheDocument();
    expect(await screen.findByText("Waiting to analyze")).toBeInTheDocument();
  });

  it("blocks reports and explains a mixed frontend/backend deployment", async () => {
    api.getCurrentMedicalInsights.mockRejectedValue(new ApplicationUpdateIncompleteError({
      frontendCommit: "frontend-new",
      backendCommit: "backend-old",
      parserVersion: "document-parser-v1",
      analysisPipelineVersion: "medical-insights-v1",
      insightContractVersion: "medical-insights-v1",
      analysisModel: "extractive-v1",
    }));
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);

    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent("Application update incomplete");
    expect(screen.getByText("backend-old")).toBeInTheDocument();
    expect(screen.getByText("document-parser-v1")).toBeInTheDocument();
    expect(screen.queryByText("About this paper")).not.toBeInTheDocument();
    expect(screen.queryByText(/ary Gb3/)).not.toBeInTheDocument();
  });

  it("prioritizes reader content and keeps unavailable study fields collapsed", async () => {
    api.getCurrentMedicalInsights.mockResolvedValue({
      ...queuedRun(),
      status: "succeeded",
      report: {
        schema_version: "medical-insights-v3",
        document_kind: "research_paper",
        language: "en",
        overview: {
          title: "Fabry disease biomarker study",
          summary: "The study examined biomarkers in adults with Fabry disease.",
          study_type: "Research paper",
          evidence_ids: [],
        },
        study_methods: {
          design: {},
          population: {},
          human_animal_in_vitro: {},
          sample_size: {},
          comparator: {},
        },
        key_findings: [{
          id: "finding-1",
          statement: "The measured biomarker differed between groups.",
          plain_explanation: "This is directly reported.",
          evidence_ids: [],
          evidence_level: "reported_in_document",
          interpretation_type: "direct_statement",
        }],
        limitations: [],
        medical_terms: [],
        what_it_means: [],
        what_it_does_not_mean: [],
        applicability: [],
        future_research: [],
        question_suggestions: [{
          id: "question-1",
          question: "Who was included in this study?",
          rationale: "The study population affects who the findings describe.",
          category: "applicability",
          evidence_ids: [],
          interpretation_type: "inference",
        }],
        questions_for_professional: [],
        warnings: ["extractive_output"],
      },
      evidence: [],
    });
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);

    renderPanel();

    const about = await screen.findByRole("heading", { name: "About this paper" });
    const findings = screen.getByRole("heading", { name: "Key findings" });
    const question = screen.getByRole("heading", { name: "Questions for your clinician" });
    expect(about.compareDocumentPosition(findings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(findings.compareDocumentPosition(question) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("The measured biomarker differed between groups.")).toBeInTheDocument();
    expect(screen.queryByText("Supported")).not.toBeInTheDocument();
    expect(screen.queryByText("Direct Statement")).not.toBeInTheDocument();

    const studyDetails = screen.getByText(/Study details/).closest("details");
    expect(studyDetails).not.toHaveAttribute("open");
    const unavailableDetails = screen.getByText("View unavailable fields").closest("details");
    expect(unavailableDetails).not.toHaveAttribute("open");
    expect(screen.getByText(/Study design · Not found in analyzed text/)).not.toBeVisible();
  });

  it("does not show a green validation signal for low-quality source passages", async () => {
    api.getCurrentMedicalInsights.mockResolvedValue({
      ...queuedRun(),
      status: "succeeded",
      citation_coverage: 1,
      report: {
        schema_version: "medical-insights-v3",
        document_kind: "research_paper",
        language: "en",
        overview: {
          title: "Fabry disease biomarker study",
          summary: "The study examined biomarkers in adults with Fabry disease.",
          study_type: "Research paper",
          evidence_ids: ["EVIDENCE_001"],
        },
        study_methods: {},
        key_findings: [],
        limitations: [],
        medical_terms: [],
        what_it_means: [],
        what_it_does_not_mean: [],
        applicability: [],
        future_research: [],
        question_suggestions: [],
        questions_for_professional: [],
        warnings: ["evidence_quality_filtered"],
      },
      evidence: [{
        evidence_id: "EVIDENCE_001",
        quote: "A damaged source passage.",
        page_start: 1,
        section_type: "results",
        quality_score: 35,
        quality_flags: ["obvious_column_interleave"],
      }],
    });
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);

    renderPanel();

    expect(await screen.findByText("Source passages attached")).toBeInTheDocument();
    expect(screen.queryByText("All displayed claims have validated source passages")).not.toBeInTheDocument();
  });

  it("shows each processing note only once", async () => {
    api.getCurrentMedicalInsights.mockResolvedValue({
      ...queuedRun(),
      status: "succeeded",
      warnings: ["evidence_quality_filtered", "evidence_quality_filtered"],
      report: {
        schema_version: "medical-insights-v3",
        document_kind: "research_paper",
        language: "en",
        overview: {
          title: "Fabry disease biomarker study",
          summary: "The study examined biomarkers in adults with Fabry disease.",
          study_type: "Research paper",
          evidence_ids: [],
        },
        study_methods: {},
        key_findings: [],
        limitations: [],
        medical_terms: [],
        what_it_means: [],
        what_it_does_not_mean: [],
        applicability: [],
        future_research: [],
        question_suggestions: [],
        questions_for_professional: [],
        warnings: ["evidence_quality_filtered"],
      },
      evidence: [],
    });
    api.getMedicalInsightConfig.mockResolvedValue(localConfig);

    renderPanel();

    expect(await screen.findAllByText("Processing notes")).toHaveLength(1);
    const noteText =
      "Some passages were excluded because their text quality was not reliable enough for medical evidence.";
    const notes = screen.getAllByText(noteText);
    expect(notes).toHaveLength(1);
    expect(notes.every((note) => note.textContent === noteText)).toBe(true);
  });
});
