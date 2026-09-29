import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DiseaseGuidePage from "../components/DiseaseGuidePage";

const api = vi.hoisted(() => ({
  getDiseaseGuide: vi.fn(),
  searchDiseaseGuides: vi.fn(),
}));

vi.mock("../services/api", () => api);

const source = {
  id: "medlineplus-genetics",
  title: "Fabry disease",
  organization: "MedlinePlus Genetics",
  url: "https://medlineplus.gov/genetics/condition/fabry-disease/",
  published_at: null,
  checked_at: "2026-09-30",
  source_type: "institutional" as const,
};

const guide = {
  schema_version: "disease-guide-v1" as const,
  concept_id: "mesh:D000795",
  language: "zh-CN" as const,
  region: "JP",
  region_status: "verified" as const,
  region_note: "",
  reviewed_at: "2026-09-30",
  title: "法布雷病",
  preferred_name_en: "Fabry disease",
  preferred_name_zh: "法布雷病",
  overview: {
    text: "法布雷病是一种遗传性溶酶体贮积病。",
    source_ids: [source.id],
  },
  topics: [
    {
      id: "what_is",
      title: "认识疾病",
      question: "它是什么，为什么会发生？",
      summary: { text: "它与 GLA 基因有关。", source_ids: [source.id] },
      key_points: [{
        id: "point-1",
        text: "某些脂质可能在细胞内积累。",
        qualifier: "这是疾病机制概览。",
        evidence_status: "established" as const,
        evidence_stage: "已有疾病机制资料",
        applicability: "",
        region: "",
        source_ids: [source.id],
      }],
    },
    {
      id: "treatments",
      title: "现有治疗方向",
      question: "目前有哪些治疗方向？",
      summary: { text: "治疗需要专业团队评估。", source_ids: [source.id] },
      key_points: [{
        id: "point-2",
        text: "酶替代治疗是一个临床方向。",
        qualifier: "本条只核对日本资料。",
        evidence_status: "established" as const,
        evidence_stage: "已用于临床",
        applicability: "",
        region: "JP",
        source_ids: [source.id],
      }],
    },
  ],
  sources: [source],
};

function wrapper({ children }: PropsWithChildren) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("DiseaseGuidePage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("starts with disease search and opens a source-backed public guide", async () => {
    const user = userEvent.setup();
    const onOpenMySources = vi.fn();
    const onOpenResearch = vi.fn();
    api.searchDiseaseGuides.mockResolvedValue({
      items: [{
        concept_id: "mesh:D000795",
        preferred_name_en: "Fabry disease",
        preferred_name_zh: "法布雷病",
        matched_alias: "法布雷病",
        guide_status: "available",
        guide_languages: ["zh-CN"],
      }],
    });
    api.getDiseaseGuide.mockResolvedValue(guide);

    render(
      <DiseaseGuidePage onOpenMySources={onOpenMySources} onOpenResearch={onOpenResearch} />,
      { wrapper },
    );

    expect(screen.getByRole("heading", { name: "你想了解什么疾病？" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("搜索疾病名称，例如：法布雷病"), "法布雷");
    const result = (await screen.findAllByRole("button", { name: /法布雷病 Fabry disease/ }))[0];
    await user.click(result);

    expect(await screen.findByRole("heading", { name: "法布雷病" })).toBeInTheDocument();
    expect(screen.getByText("一句话认识")).toBeInTheDocument();
    expect(screen.getByText("认识疾病")).toBeInTheDocument();
    expect(screen.getAllByText("已有认识")[0]).toBeInTheDocument();

    const sourceButton = screen.getAllByRole("button", { name: /查看来源 · MedlinePlus Genetics/ })[0];
    await user.click(sourceButton);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Fabry disease" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开原始来源/ })).toHaveAttribute("href", source.url);

    await user.click(screen.getByRole("button", { name: "关闭来源" }));
    await user.click(screen.getByRole("button", { name: /查看研究依据/ }));
    expect(onOpenResearch).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: /上传自己的资料/ }));
    expect(onOpenMySources).toHaveBeenCalledTimes(1);
  });

  it("shows a clear preparing state when a concept has no public guide", async () => {
    const user = userEvent.setup();
    api.searchDiseaseGuides.mockResolvedValue({
      items: [{
        concept_id: "mesh:D003920",
        preferred_name_en: "Diabetes Mellitus",
        preferred_name_zh: "糖尿病",
        matched_alias: "糖尿病",
        guide_status: "preparing",
        guide_languages: [],
      }],
    });

    render(<DiseaseGuidePage onOpenMySources={vi.fn()} onOpenResearch={vi.fn()} />, { wrapper });
    await user.type(screen.getByPlaceholderText("搜索疾病名称，例如：法布雷病"), "糖尿病");
    await user.click((await screen.findAllByRole("button", { name: /糖尿病 Diabetes Mellitus/ }))[0]);

    expect(await screen.findByText(/公共指南正在准备中/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开研究工具" })).toBeInTheDocument();
    expect(api.getDiseaseGuide).not.toHaveBeenCalled();
  });
});
