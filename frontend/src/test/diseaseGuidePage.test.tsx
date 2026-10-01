import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
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
  language: "en",
  usage_note: "用于说明疾病基本概念。",
};

const referenceSource = {
  id: "genereviews-fabry",
  title: "Fabry Disease - GeneReviews",
  organization: "NCBI Bookshelf",
  url: "https://www.ncbi.nlm.nih.gov/books/NBK1292/",
  published_at: null,
  checked_at: "2026-09-30",
  source_type: "reference" as const,
  language: "en",
  usage_note: "用于补充疾病机制和遗传信息。",
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
    source_ids: [source.id, referenceSource.id],
  },
  topics: [
    {
      id: "what_is",
      title: "认识疾病",
      question: "这个病是什么，为什么会发生？",
      summary: { text: "它与 GLA 基因有关。", source_ids: [source.id, referenceSource.id] },
      key_points: [{
        id: "point-1",
        text: "某些脂质可能在细胞内积累。",
        qualifier: "这是疾病机制概览。",
        evidence_status: "established" as const,
        evidence_stage: "已有疾病机制资料",
        applicability: "",
        region: "",
        source_ids: [source.id, referenceSource.id],
      }],
      terms: [{
        id: "gla-gene",
        label: "GLA 基因",
        definition: { text: "影响细胞处理某些脂质能力的基因。", source_ids: [source.id] },
        context: { text: "它位于 X 染色体上。", source_ids: [referenceSource.id] },
      }],
    },
    {
      id: "treatments",
      title: "治疗方向",
      question: "目前有哪些治疗方向？",
      summary: { text: "治疗需要专业团队评估。", source_ids: [source.id, referenceSource.id] },
      key_points: [{
        id: "point-2",
        text: "酶替代治疗是一个临床方向。",
        qualifier: "本条只核对日本资料。",
        evidence_status: "established" as const,
        evidence_stage: "已用于临床",
        applicability: "",
        region: "JP",
        source_ids: [source.id, referenceSource.id],
      }],
    },
    {
      id: "research_progress",
      title: "研究进展",
      question: "新方法研究到哪一步了？",
      summary: { text: "研究登记状态会变化。", source_ids: [referenceSource.id] },
      key_points: [{
        id: "point-3",
        text: "有些新方法仍在研究中。",
        qualifier: "登记不等于疗效已经证实。",
        evidence_status: "clinical_research" as const,
        evidence_stage: "临床研究登记",
        applicability: "",
        region: "国际登记",
        source_ids: [referenceSource.id],
        research_context: {
          evidence_kind: "registry" as const,
          goal: { text: "了解研究想解决的问题。", source_ids: [referenceSource.id] },
          current: { text: "目前只有登记信息可核对。", source_ids: [referenceSource.id] },
          unknown: { text: "结果仍需后续研究确认。", source_ids: [referenceSource.id] },
        },
      }],
    },
  ],
  sources: [source, referenceSource],
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
      <DiseaseGuidePage onOpenMySources={onOpenMySources} />,
      { wrapper },
    );

    expect(screen.getByRole("heading", { name: "你想了解什么疾病？" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("搜索疾病名称，例如：法布雷病"), "法布雷");
    const result = (await screen.findAllByRole("button", { name: /法布雷病 Fabry disease/ }))[0];
    await user.click(result);

    expect(await screen.findByRole("heading", { name: "法布雷病" })).toBeInTheDocument();
    expect(screen.getByText("先认识这个病")).toBeInTheDocument();
    const startButton = screen.getByRole("button", { name: "从基础开始了解" });
    await user.click(startButton);
    expect(document.getElementById("guide-topic-what_is")).toHaveAttribute("open");
    expect(document.getElementById("guide-topic-what_is")?.querySelector("summary")).toHaveFocus();
    await user.click(screen.getByText("GLA 基因是什么意思？"));
    expect(screen.getByText("影响细胞处理某些脂质能力的基因。")).toBeInTheDocument();
    expect(screen.getByText("它位于 X 染色体上。")).toBeInTheDocument();

    const nextTopicButton = screen.getByRole("button", { name: "接着了解：目前有哪些治疗方向？" });
    await user.click(nextTopicButton);
    expect(document.getElementById("guide-topic-treatments")).toHaveAttribute("open");
    expect(document.getElementById("guide-topic-treatments")?.querySelector("summary")).toHaveFocus();
    expect(screen.getAllByRole("button", { name: "打开主题：这个病是什么，为什么会发生？" })[0]).toBeInTheDocument();
    expect(screen.getByText("某些脂质可能在细胞内积累。")).toBeInTheDocument();

    const treatmentNav = screen.getAllByRole("button", { name: "打开主题：目前有哪些治疗方向？" })[0];
    await user.click(treatmentNav);
    const treatmentTopic = document.getElementById("guide-topic-treatments");
    expect(treatmentTopic).toHaveAttribute("open");
    expect(treatmentTopic?.querySelector("summary")).toHaveFocus();
    expect(screen.getByText("已用于临床")).toBeInTheDocument();
    expect(screen.getByText("JP")).toBeInTheDocument();

    const researchNav = screen.getAllByRole("button", { name: "打开主题：新方法研究到哪一步了？" })[0];
    await user.click(researchNav);
    expect(screen.getByText("临床研究登记")).toBeInTheDocument();
    expect(screen.getByText("国际登记")).toBeInTheDocument();
    expect(screen.getByText("想解决什么问题")).toBeInTheDocument();
    expect(screen.getByText("了解研究想解决的问题。")).toBeInTheDocument();
    expect(screen.getByText("目前只有登记信息可核对。")).toBeInTheDocument();
    expect(screen.getByText("还有哪些不确定")).toBeInTheDocument();

    const sourceButton = screen.getAllByRole("button", { name: /查看依据 1：MedlinePlus Genetics/ })[0];
    await user.click(sourceButton);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Fabry disease" })).toBeInTheDocument();
    expect(screen.getByText("资料语言：英文")).toBeInTheDocument();
    expect(screen.getByText("本指南使用它来：用于说明疾病基本概念。")).toBeInTheDocument();
    const closeButton = screen.getByRole("button", { name: "关闭来源" });
    const sourceLink = screen.getByRole("link", { name: /打开原始来源/ });
    expect(sourceLink).toHaveAttribute("href", source.url);

    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab();
    expect(sourceLink).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(sourceLink).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(sourceButton).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "回到主题目录" }));
    expect(screen.getAllByRole("button", { name: "打开主题：这个病是什么，为什么会发生？" })[0]).toHaveFocus();

    const sourceActions = screen.getAllByRole("button", { name: /查看本指南参考资料/ });
    await user.click(sourceActions[sourceActions.length - 1]);
    expect(screen.getByRole("heading", { name: "本指南参考资料" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Fabry disease/ })).toHaveAttribute("href", source.url);
    await user.click(screen.getByRole("button", { name: /上传自己的资料/ }));
    expect(onOpenMySources).toHaveBeenCalledTimes(1);
  });

  it("keeps source numbering stable and reports search failures", async () => {
    const user = userEvent.setup();
    api.searchDiseaseGuides.mockRejectedValue(new Error("network"));

    render(<DiseaseGuidePage onOpenMySources={vi.fn()} />, { wrapper });
    await user.type(screen.getByPlaceholderText("搜索疾病名称，例如：法布雷病"), "法布雷");
    expect(await screen.findByText("疾病搜索暂时不可用，请稍后再试。")).toBeInTheDocument();

    cleanup();
    api.searchDiseaseGuides.mockResolvedValue({ items: [] });
    api.getDiseaseGuide.mockResolvedValue(guide);
    render(<DiseaseGuidePage onOpenMySources={vi.fn()} />, { wrapper });
    await user.click(screen.getByRole("button", { name: /法布雷病 Fabry disease/ }));
    await screen.findByRole("heading", { name: "法布雷病" });
    expect(screen.getAllByRole("button", { name: /查看依据 1：MedlinePlus Genetics/ }).length).toBeGreaterThan(1);
    expect(screen.getAllByRole("button", { name: /查看依据 2：NCBI Bookshelf/ }).length).toBeGreaterThan(1);
  });

  it("reopens the introductory topic for a fresh guide and preserves manual collapse", async () => {
    const user = userEvent.setup();
    api.getDiseaseGuide.mockResolvedValue(guide);

    render(<DiseaseGuidePage onOpenMySources={vi.fn()} />, { wrapper });
    await user.click(screen.getByRole("button", { name: /法布雷病 Fabry disease/ }));
    await screen.findByRole("heading", { name: "法布雷病" });

    const getIntroTopic = () => document.getElementById("guide-topic-what_is") as HTMLDetailsElement | null;
    expect(getIntroTopic()?.open).toBe(true);

    const introSummary = getIntroTopic()?.querySelector("summary");
    expect(introSummary).not.toBeNull();
    await user.click(introSummary as HTMLElement);
    expect(getIntroTopic()?.open).toBe(false);

    await user.click(screen.getAllByRole("button", { name: /查看依据 1：MedlinePlus Genetics/ })[0]);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(getIntroTopic()?.open).toBe(false);

    await user.click(screen.getByRole("button", { name: "返回疾病搜索" }));
    await user.click(screen.getByRole("button", { name: /法布雷病 Fabry disease/ }));
    await screen.findByRole("heading", { name: "法布雷病" });
    expect(getIntroTopic()?.open).toBe(true);
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

    const onOpenMySources = vi.fn();
    render(<DiseaseGuidePage onOpenMySources={onOpenMySources} />, { wrapper });
    await user.type(screen.getByPlaceholderText("搜索疾病名称，例如：法布雷病"), "糖尿病");
    await user.click((await screen.findAllByRole("button", { name: /糖尿病 Diabetes Mellitus/ }))[0]);

    expect(await screen.findByText(/公共指南正在准备中/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "返回疾病搜索" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "查看我的资料" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看我的资料" }));
    expect(onOpenMySources).toHaveBeenCalledTimes(1);
    expect(api.getDiseaseGuide).not.toHaveBeenCalled();
  });

  it("does not offer an unverified region selector for Japan-only treatment information", async () => {
    const user = userEvent.setup();
    api.getDiseaseGuide.mockResolvedValue(guide);

    render(
      <DiseaseGuidePage onOpenMySources={vi.fn()} />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /法布雷病 Fabry disease/ }));

    expect(await screen.findByText("治疗信息按日本资料核查")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "地区" })).not.toBeInTheDocument();
    expect(api.getDiseaseGuide).toHaveBeenCalledWith("mesh:D000795", "zh-CN", "JP");
  });

  it("keeps additional parent sources accessible in research cards", async () => {
    const user = userEvent.setup();
    const guideWithExtraSource = structuredClone(guide);

    const researchPoint = guideWithExtraSource.topics
      .find((topic) => topic.id === "research_progress")
      ?.key_points[0];

    if (!researchPoint) {
      throw new Error("Research point fixture is missing");
    }

    researchPoint.source_ids = [referenceSource.id, source.id];

    api.searchDiseaseGuides.mockResolvedValue({ items: [] });
    api.getDiseaseGuide.mockResolvedValue(guideWithExtraSource);

    render(
      <DiseaseGuidePage onOpenMySources={vi.fn()} />,
      { wrapper },
    );

    await user.click(
      screen.getByRole("button", {
        name: /法布雷病 Fabry disease/,
      }),
    );

    await screen.findByRole("heading", { name: "法布雷病" });

    await user.click(
      screen.getAllByRole("button", {
        name: "打开主题：新方法研究到哪一步了？",
      })[0],
    );

    const article = screen
      .getByText("登记不等于疗效已经证实。")
      .closest("article");

    if (!article) {
      throw new Error("Research card is missing");
    }

    const card = within(article);
    const extraSourceButton = card.getByRole("button", {
      name: /查看依据 1：MedlinePlus Genetics/,
    });

    expect(extraSourceButton).toBeVisible();
    expect(
      card.getAllByRole("button", {
        name: /查看依据 2：NCBI Bookshelf/,
      }).length,
    ).toBeGreaterThan(0);

    await user.click(extraSourceButton);

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("link", {
        name: /打开原始来源/,
      }),
    ).toHaveAttribute("href", source.url);

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    expect(extraSourceButton).toHaveFocus();
  });
});
