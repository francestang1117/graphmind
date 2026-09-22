import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import MedicalInsightPanel from "../components/upload/MedicalInsightPanel";

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
  model_name: "extractive-v2",
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
    model_name: "extractive-v2",
    prompt_version: "medical-insights-v3+medical-insights-readable-v2",
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
});
