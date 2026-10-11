import { ArrowLeft, BookOpen, ExternalLink, Search, ShieldCheck, Upload, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import MedicalTerm from "./MedicalTerm";
import DiseaseTopicMap from "./disease-guide/DiseaseTopicMap";
import { useDiseaseGuide, useDiseaseGuideSearch } from "../hooks/useDiseaseGuide";
import "../styles/diseaseGuideReading.css";
import type {
  DiseaseGuidePoint,
  DiseaseGuideSearchItem,
  DiseaseGuideSource,
  DiseaseGuideTerm,
} from "../services/api";

interface DiseaseGuidePageProps {
  onOpenMySources: () => void;
}

const FABRY_CONCEPT_ID = "mesh:D000795";

const evidenceLabels: Record<DiseaseGuidePoint["evidence_status"], string> = {
  established: "已有认识",
  clinical_research: "临床研究",
  early_exploration: "早期探索",
};

const researchEvidenceLabels: Record<NonNullable<DiseaseGuidePoint["research_context"]>["evidence_kind"], string> = {
  registry: "研究登记信息",
  published_results: "已公布研究结果",
  review: "综述资料",
};

const sourceLanguageLabels: Record<string, string> = {
  "zh-CN": "中文",
  en: "英文",
  ja: "日文",
};

const sourceGroupDefinitions: Array<{
  label: string;
  types: DiseaseGuideSource["source_type"][];
}> = [
  { label: "疾病基础资料", types: ["institutional", "reference"] },
  { label: "日本药品资料", types: ["regulatory"] },
  { label: "研究登记", types: ["clinical_registry"] },
];

function scrollToGuideSources() {
  const target = document.getElementById("disease-guide-sources");
  if (target && typeof target.scrollIntoView === "function") {
    target.scrollIntoView({ behavior: preferredScrollBehavior(), block: "start" });
  }
}

function preferredScrollBehavior(): ScrollBehavior {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

function scrollToGuideDirectory() {
  const target = document.getElementById("disease-guide-topic-directory");
  if (!target) return;

  target.scrollIntoView?.({ behavior: preferredScrollBehavior(), block: "start" });
  target.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
}

function scrollToGuideOverview() {
  document.getElementById("disease-guide-overview-title")?.scrollIntoView?.({
    behavior: preferredScrollBehavior(),
    block: "start",
  });
}

function openGuideTopic(topicId: string) {
  const target = document.getElementById(`guide-topic-${topicId}`);
  if (!(target instanceof HTMLDetailsElement)) return;

  target.open = true;
  target.querySelector<HTMLElement>("summary")?.focus({ preventScroll: true });
  target.scrollIntoView?.({ block: "start" });
}

function DiseaseGuidePage({ onOpenMySources }: DiseaseGuidePageProps) {
  const [query, setQuery] = useState("");
  const [selectedConcept, setSelectedConcept] = useState<DiseaseGuideSearchItem | null>(null);
  const [activeTopicId, setActiveTopicId] = useState<string | null>(null);
  const [openSourceId, setOpenSourceId] = useState<string | null>(null);
  const sourceDrawerRef = useRef<HTMLElement | null>(null);
  const sourceTriggerRef = useRef<HTMLButtonElement | null>(null);
  const sourceWasOpenRef = useRef(false);
  const searchQuery = useDiseaseGuideSearch(query);
  const guideQuery = useDiseaseGuide(
    selectedConcept?.guide_status === "available" ? selectedConcept.concept_id : null,
    "zh-CN",
    "JP",
  );
  const selectedSource = useMemo<DiseaseGuideSource | null>(() => {
    if (!guideQuery.data || !openSourceId) return null;
    return guideQuery.data.sources.find((source) => source.id === openSourceId) ?? null;
  }, [guideQuery.data, openSourceId]);
  const firstTopic = guideQuery.data?.topics.find((topic) => topic.id === "what_is")
    ?? guideQuery.data?.topics[0]
    ?? null;
  const firstTopicId = firstTopic?.id ?? null;

  useLayoutEffect(() => {
    if (!("IntersectionObserver" in window) || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      return undefined;
    }

    const sections = document.querySelectorAll<HTMLElement>(".kw-shell-guide .disease-guide-reveal");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.08, rootMargin: "0px 0px 48px 0px" });

    sections.forEach((section) => {
      section.classList.add("is-motion-ready");
      observer.observe(section);
    });
    return () => {
      observer.disconnect();
      sections.forEach((section) => section.classList.remove("is-motion-ready"));
    };
  }, [selectedConcept, guideQuery.data]);

  const openSource = useCallback((sourceId: string, trigger: HTMLButtonElement) => {
    sourceTriggerRef.current = trigger;
    setOpenSourceId(sourceId);
  }, []);

  const closeSource = useCallback(() => {
    setOpenSourceId(null);
  }, []);

  const setInitialTopicOpen = useCallback((element: HTMLDetailsElement | null) => {
    if (element) {
      element.open = true;
      setActiveTopicId(firstTopicId);
    }
  }, [firstTopicId]);

  const selectGuideTopic = useCallback((topicId: string) => {
    setActiveTopicId(topicId);
    openGuideTopic(topicId);
  }, []);

  useEffect(() => {
    if (!selectedSource) {
      if (sourceWasOpenRef.current) {
        sourceWasOpenRef.current = false;
        sourceTriggerRef.current?.focus();
      }
      return undefined;
    }

    sourceWasOpenRef.current = true;
    const drawer = sourceDrawerRef.current;
    if (!drawer) return undefined;

    drawer.focus();
    const focusableSelector = "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])";
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeSource();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector));
      if (focusable.length === 0) {
        event.preventDefault();
        drawer.focus();
        return;
      }

      const currentIndex = focusable.indexOf(document.activeElement as HTMLElement);
      if (event.shiftKey && (currentIndex <= 0 || currentIndex === -1)) {
        event.preventDefault();
        focusable[focusable.length - 1].focus();
      } else if (!event.shiftKey && (currentIndex === focusable.length - 1 || currentIndex === -1)) {
        event.preventDefault();
        focusable[0].focus();
      }
    };
    const keepFocusInside = (event: FocusEvent) => {
      if (!drawer.contains(event.target as Node)) drawer.focus();
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("focusin", keepFocusInside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("focusin", keepFocusInside);
    };
  }, [closeSource, selectedSource]);

  const openFabryGuide = () => {
    setSelectedConcept({
      concept_id: FABRY_CONCEPT_ID,
      preferred_name_en: "Fabry disease",
      preferred_name_zh: "法布雷病",
      matched_alias: "法布雷病",
      guide_status: "available",
      guide_languages: ["zh-CN"],
    });
    setActiveTopicId(null);
    sourceTriggerRef.current = null;
    setOpenSourceId(null);
  };

  const selectConcept = (concept: DiseaseGuideSearchItem) => {
    setSelectedConcept(concept);
    setActiveTopicId(null);
    sourceTriggerRef.current = null;
    setOpenSourceId(null);
  };

  if (!selectedConcept) {
    return (
      <div className="disease-guide-page">
        <section className="disease-guide-search-hero" aria-labelledby="disease-guide-title">
          <div className="disease-guide-hero-copy">
            <span className="disease-guide-eyebrow">GRAPHMIND / 疾病探索</span>
            <h2 id="disease-guide-title">从一个问题，<br />慢慢认识一种疾病。</h2>
            <p>从病因、身体影响到治疗与研究进展，把分散的资料连起来，读懂有来源的解释。</p>
            <label className="disease-guide-search-box">
              <Search size={20} aria-hidden="true" />
              <span className="sr-only">搜索疾病</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索疾病名称，例如：法布雷病"
                autoComplete="off"
              />
            </label>
            {query.trim().length >= 2 && (
              <div className="disease-guide-search-results" aria-live="polite">
                {searchQuery.isLoading && <p className="disease-guide-muted">正在搜索本地疾病词典…</p>}
                {searchQuery.isError && <p className="disease-guide-error">疾病搜索暂时不可用，请稍后再试。</p>}
                {!searchQuery.isLoading && !searchQuery.isError && searchQuery.data?.items.length === 0 && (
                  <p className="disease-guide-muted">没有找到匹配的疾病名称。</p>
                )}
                {searchQuery.data?.items.map((concept) => (
                  <button
                    type="button"
                    className="disease-guide-search-result"
                    key={concept.concept_id}
                    onClick={() => selectConcept(concept)}
                  >
                    <span>
                      <strong>{concept.preferred_name_zh || concept.preferred_name_en}</strong>
                      <small>{concept.preferred_name_en}</small>
                    </span>
                    <span className={`disease-guide-result-status ${concept.guide_status}`}>
                      {concept.guide_status === "available" ? "查看指南" : "指南准备中"}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="disease-guide-example">
              <span>先试读一份指南</span>
              <button type="button" onClick={openFabryGuide}>认识法布雷病 <span aria-hidden="true">↗</span></button>
            </div>
          </div>
          <div className="disease-guide-hero-art" aria-hidden="true">
            <svg viewBox="0 0 500 500" focusable="false">
              <path d="M254 250 C182 180 159 157 108 127 M254 250 C320 181 343 153 397 118 M254 250 C173 296 149 336 112 374 M254 250 C330 305 355 329 395 377" />
              <circle cx="254" cy="250" r="92" />
              <circle cx="108" cy="127" r="8" />
              <circle cx="397" cy="118" r="8" />
              <circle cx="112" cy="374" r="8" />
              <circle cx="395" cy="377" r="8" />
            </svg>
            <span className="disease-guide-art-core">一种疾病<br /><strong>多种线索</strong></span>
            <span className="disease-guide-art-label cause">为什么发生</span>
            <span className="disease-guide-art-label impact">会怎样影响身体</span>
            <span className="disease-guide-art-label treatment">有哪些治疗方向</span>
            <span className="disease-guide-art-label research">研究走到哪一步</span>
          </div>
        </section>
        <section className="disease-guide-journey disease-guide-reveal" aria-label="阅读路径">
          <div><span>01 / 认识</span><strong>先看懂疾病本身</strong><p>从通俗概览开始，无须先读论文。</p></div>
          <div><span>02 / 探索</span><strong>按关心的问题阅读</strong><p>症状、治疗和研究可以分开看。</p></div>
          <div><span>03 / 核查</span><strong>随时打开原始来源</strong><p>每个重要说法都有可追溯的依据。</p></div>
        </section>
        <section className="disease-guide-secondary-entry disease-guide-reveal" aria-label="其他入口">
          <div>
            <span className="disease-guide-eyebrow">可选入口</span>
            <h3>也可以先查看自己的资料</h3>
            <p>上传论文或指南是研究工具的一部分，不是了解疾病的前提。</p>
          </div>
          <button type="button" className="disease-guide-secondary-action" onClick={onOpenMySources}>
            <Upload size={16} />
            打开我的资料
          </button>
        </section>
      </div>
    );
  }

  if (selectedConcept.guide_status === "preparing") {
    return (
      <div className="disease-guide-page">
        <button type="button" className="disease-guide-back" onClick={() => setSelectedConcept(null)}>
          <ArrowLeft size={16} /> 返回疾病搜索
        </button>
        <section className="disease-guide-empty-state">
          <BookOpen size={30} />
          <h2>{selectedConcept.preferred_name_zh || selectedConcept.preferred_name_en}</h2>
          <p>已识别这个疾病概念，但公共指南正在准备中，目前还没有经过核查的通俗指南。</p>
          <button type="button" className="disease-guide-primary-action" onClick={() => setSelectedConcept(null)}>
            <ArrowLeft size={16} /> 返回疾病搜索
          </button>
          <button type="button" className="disease-guide-text-action" onClick={onOpenMySources}>
            <Upload size={16} /> 查看我的资料
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="disease-guide-page disease-guide-page-reading">
      <button type="button" className="disease-guide-back" onClick={() => setSelectedConcept(null)}>
        <ArrowLeft size={16} /> 返回疾病搜索
      </button>
      {guideQuery.isLoading && <div className="disease-guide-loading">正在打开指南…</div>}
      {guideQuery.isError && (
        <section className="disease-guide-empty-state">
          <BookOpen size={30} />
          <h2>指南暂时无法打开</h2>
          <p>请稍后再试。研究工具仍可从侧栏进入。</p>
        </section>
      )}
      {guideQuery.data && (
        <>
          <header className="disease-guide-header">
            <div className="disease-guide-cover-illustration illustration-orbit" aria-hidden="true">
              <svg viewBox="0 0 380 420" fill="none" focusable="false">
                <defs>
                  <clipPath id="guide-orbit-interior">
                    <path d="M98 152c13-45 60-75 103-63 44 12 69 58 56 99-14 43-62 70-103 55-43-15-69-51-56-91Z" />
                  </clipPath>
                </defs>
                <g className="guide-art-orbit">
                  <path d="M-60 130C35-34 241-27 314 104c74 133-35 265-157 237C37 314 8 172 100 105" stroke="#E79DB5" strokeWidth="52" strokeLinecap="round" />
                  <path d="M-48 129C41-19 230-7 296 108" stroke="#AF597A" strokeWidth="2" opacity=".82" />
                  <path d="M-45 361C65 275 183 278 270 374" stroke="#4B9EA5" strokeWidth="16" strokeLinecap="round" />
                  <path d="M98 152c13-45 60-75 103-63 44 12 69 58 56 99-14 43-62 70-103 55-43-15-69-51-56-91Z" fill="#D3EBEF" />
                  <g clipPath="url(#guide-orbit-interior)" opacity=".4">
                    <path d="M72 207 210 68M80 224 228 76M96 240 244 92M114 252 260 108M136 261 272 125M159 268 279 148" stroke="#4B9EA5" strokeWidth="2" />
                  </g>
                  <path d="M132 166c7-22 30-35 51-27 22 8 33 29 26 49-7 20-29 31-49 24-21-7-36-27-28-46Z" fill="#4D85B8" />
                  <path d="M154 161c14-11 34-7 42 8" stroke="#E5F4FA" strokeWidth="3" strokeLinecap="round" />
                  <path d="M235 85c12-8 23-9 33-5M276 90l8 8M281 271l14-7" stroke="#356D68" strokeWidth="2" strokeLinecap="round" opacity=".66" />
                  <circle cx="277" cy="321" r="6" fill="#D99149" />
                </g>
              </svg>
            </div>
            <div className="disease-guide-cover-illustration illustration-pages" aria-hidden="true">
              <svg viewBox="0 0 380 420" fill="none" focusable="false">
                <defs>
                  <clipPath id="guide-paper-diagram">
                    <path d="M145 276c3-66 59-113 117-105 60 7 91 55 90 115-2 67-59 109-118 101-60-8-92-49-89-111Z" />
                  </clipPath>
                </defs>
                <g className="guide-art-paper-back">
                  <path d="M131 28 399 94 321 428 55 361Z" fill="#AFCFE5" />
                  <path d="M60 131 302 16 425 288 171 416Z" fill="#B6DFC9" />
                  <path d="M79 141 303 35" stroke="#79B3A0" strokeWidth="2" opacity=".75" />
                </g>
                <g className="guide-art-paper-front">
                  <path d="M100 69 339 39 382 357 136 392Z" fill="#FFE7C6" />
                  <path d="M133 108 179 102" stroke="#44998F" strokeWidth="9" strokeLinecap="round" />
                  <path d="M136 137 298 116M141 158l119-15" stroke="#87B8A9" strokeWidth="5" strokeLinecap="round" />
                  <path d="M145 276c3-66 59-113 117-105 60 7 91 55 90 115-2 67-59 109-118 101-60-8-92-49-89-111Z" fill="#DF9865" />
                  <g clipPath="url(#guide-paper-diagram)">
                    <path d="M150 353c68-4 134-59 158-135M128 310c62-5 114-43 138-107" stroke="#FFE7C6" strokeWidth="14" strokeLinecap="round" />
                    <path d="M164 388c59-19 118-59 160-116" stroke="#BB725E" strokeWidth="3" opacity=".5" />
                    <path d="m264 184 115 111m-123-94 115 111m-121-96 110 107m-110-89 104 101m-105-81 93 91" stroke="#BB725E" strokeWidth="1.5" opacity=".37" />
                  </g>
                  <path d="M157 365h60" stroke="#44998F" strokeWidth="3" strokeLinecap="round" opacity=".7" />
                </g>
              </svg>
            </div>
            <div className="disease-guide-cover-type">
              <span className="disease-guide-eyebrow">GRAPHMIND / 疾病阅读指南</span>
              <h2 className="disease-guide-letter-title" aria-label={guideQuery.data.title}>
                {Array.from(guideQuery.data.title).length <= 6
                  ? Array.from(guideQuery.data.title).map((letter, index) => (
                    <span className={`disease-guide-letter letter-${index % 6}`} aria-hidden="true" key={`${letter}-${index}`}>
                      <span className="disease-guide-letter-glyph">{letter}</span>
                    </span>
                  ))
                  : guideQuery.data.title}
              </h2>
              <p className="disease-guide-header-subtitle">{guideQuery.data.preferred_name_en}</p>
              <p className="disease-guide-header-deck">从第一次听说这个名字，到找到自己关心的问题。</p>
              <button type="button" className="disease-guide-cover-start" onClick={scrollToGuideOverview}>
                先读一分钟概览 <span aria-hidden="true">↓</span>
              </button>
            </div>
            <div className="disease-guide-meta">
              <span><ShieldCheck size={14} /> 内容核查至 {guideQuery.data.reviewed_at}</span>
              <span className="verified">治疗信息按日本资料核查</span>
            </div>
          </header>

          <div className="disease-guide-reading-grid">
            <aside className="disease-guide-reading-index" aria-label="阅读目录">
              <div className="disease-guide-reading-index-inner">
                <span className="disease-guide-index-label">CONTENT / 阅读目录</span>
                <DiseaseTopicMap
                  diseaseName={guideQuery.data.title}
                  topics={guideQuery.data.topics}
                  activeTopicId={activeTopicId}
                  onSelectTopic={selectGuideTopic}
                />
                <span className="disease-guide-index-note">按自己的节奏阅读 ↗</span>
              </div>
            </aside>

            <div className="disease-guide-article">
              <section className="disease-guide-overview disease-guide-reveal" aria-labelledby="disease-guide-overview-title">
                <span className="disease-guide-section-kicker">01 / THE BEGINNING</span>
                <h3 id="disease-guide-overview-title">先认识这个病</h3>
                <p>{guideQuery.data.overview.text}</p>
                <SourceLinks
                  sourceIds={guideQuery.data.overview.source_ids}
                  sources={guideQuery.data.sources}
                  onOpen={openSource}
                />
                {firstTopic && (
                  <button
                    type="button"
                    className="disease-guide-primary-action disease-guide-start-action"
                    onClick={() => selectGuideTopic(firstTopic.id)}
                  >
                    从基础开始了解 <span aria-hidden="true">↗</span>
                  </button>
                )}
              </section>

          <section className="disease-guide-topics disease-guide-reveal" aria-labelledby="disease-guide-topics-title">
            <div className="disease-guide-section-heading">
              <div>
                <span className="disease-guide-section-kicker">继续探索</span>
                <h3 id="disease-guide-topics-title">你可能还想知道</h3>
              </div>
              <span className="disease-guide-topic-count">{guideQuery.data.topics.length} 个主题</span>
            </div>
            {guideQuery.data.topics.map((topic, index) => {
              const nextTopic = guideQuery.data.topics[index + 1];
              return (
                <details
                  id={`guide-topic-${topic.id}`}
                  className="disease-guide-topic"
                  key={topic.id}
                  ref={topic.id === firstTopicId ? setInitialTopicOpen : undefined}
                  onToggle={(event) => {
                    const isOpen = event.currentTarget.open;
                    setActiveTopicId((current) => (
                      isOpen
                        ? topic.id
                        : current === topic.id ? null : current
                    ));
                  }}
                >
                  <summary>
                    <span className="disease-guide-topic-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                    <strong>{topic.question}</strong>
                    <span className="disease-guide-summary-marker" aria-hidden="true">
                      <span className="when-closed">＋</span>
                      <span className="when-open">−</span>
                    </span>
                  </summary>
                  <div className="disease-guide-topic-body">
                    <p className="disease-guide-topic-summary">{topic.summary.text}</p>
                    <SourceLinks
                      sourceIds={topic.summary.source_ids}
                      sources={guideQuery.data.sources}
                      onOpen={openSource}
                    />
                    <div className="disease-guide-points">
                      {topic.key_points.map((point) => (
                        <GuidePoint
                          key={point.id}
                          point={point}
                          sources={guideQuery.data.sources}
                          onOpenSource={openSource}
                        />
                      ))}
                    </div>
                    {topic.terms && topic.terms.length > 0 && (
                      <div className="disease-guide-terms" aria-label="术语解释">
                        <h4>术语解释</h4>
                        {topic.terms.map((term) => (
                          <MedicalTerm key={term.id} term={term}>
                            <SourceLinks
                              sourceIds={termSourceIds(term)}
                              sources={guideQuery.data.sources}
                              onOpen={openSource}
                            />
                          </MedicalTerm>
                        ))}
                      </div>
                    )}
                    <div className="disease-guide-topic-footer">
                      {nextTopic ? (
                          <button type="button" onClick={() => selectGuideTopic(nextTopic.id)}>
                          接着了解：{nextTopic.question}
                        </button>
                      ) : (
                        <button type="button" onClick={scrollToGuideSources}>
                          查看本指南参考资料
                        </button>
                      )}
                    </div>
                  </div>
                </details>
              );
            })}
          </section>
            </div>
          </div>

          <section className="disease-guide-next-step disease-guide-reveal">
            <div>
              <span className="disease-guide-section-kicker">下一步</span>
              <h3>继续了解这个病</h3>
              <p>选择一个主题继续阅读；需要核对来源时，再查看本指南使用的公开资料。</p>
            </div>
            <div className="disease-guide-next-actions" aria-label="继续阅读">
              <button type="button" className="disease-guide-topic-action" onClick={scrollToGuideDirectory}>
                回到主题目录
              </button>
              <button
                type="button"
                className="disease-guide-secondary-action"
                onClick={scrollToGuideSources}
              >
                <BookOpen size={16} /> 查看本指南参考资料
              </button>
              <button type="button" className="disease-guide-text-action" onClick={onOpenMySources}>
                <Upload size={16} /> 上传自己的资料
              </button>
            </div>
          </section>

          <section
            id="disease-guide-sources"
            className="disease-guide-sources disease-guide-reveal"
            aria-labelledby="disease-guide-sources-title"
          >
            <div className="disease-guide-section-heading">
              <div>
                <span className="disease-guide-section-kicker">可核查</span>
                <h3 id="disease-guide-sources-title">本指南参考资料</h3>
              </div>
              <span className="disease-guide-topic-count">{guideQuery.data.sources.length} 项来源</span>
            </div>
            <p className="disease-guide-sources-intro">
              每条说明都来自下列公开资料。打开原始来源可查看完整内容和最新版本。
            </p>
            <div className="disease-guide-source-groups">
              {sourceGroupDefinitions.map((group) => {
                const sources = guideQuery.data.sources.filter((source) => group.types.includes(source.source_type));
                if (sources.length === 0) return null;
                return (
                  <div className="disease-guide-source-group" key={group.label}>
                    <h4>{group.label}</h4>
                    <div className="disease-guide-source-list">
                      {sources.map((source) => {
                        const sourceNumber = guideQuery.data.sources.findIndex((item) => item.id === source.id) + 1;
                        return (
                        <article className="disease-guide-source-item" key={source.id}>
                          <a href={source.url} target="_blank" rel="noreferrer">
                            <span className="disease-guide-source-number">[{sourceNumber}]</span>
                            {source.title} <ExternalLink size={13} aria-hidden="true" />
                          </a>
                          <span>
                            {source.organization}
                            {source.language && ` · ${sourceLanguageLabels[source.language] ?? source.language}`}
                            {` · 核查至 ${source.checked_at}`}
                          </span>
                          {source.usage_note && <small>{source.usage_note}</small>}
                        </article>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {selectedSource && (
            <div className="disease-guide-source-backdrop" role="presentation" onClick={closeSource}>
              <aside
                className="disease-guide-source-drawer"
                role="dialog"
                aria-modal="true"
                aria-labelledby="disease-guide-source-title"
                ref={sourceDrawerRef}
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
              >
                <div className="disease-guide-source-heading">
                  <div>
                    <span className="disease-guide-section-kicker">来源</span>
                    <h3 id="disease-guide-source-title">{selectedSource.title}</h3>
                  </div>
                  <button type="button" className="disease-guide-icon-button" aria-label="关闭来源" onClick={closeSource}>
                    <X size={18} />
                  </button>
                </div>
                <p className="disease-guide-source-organization">{selectedSource.organization}</p>
                {selectedSource.language && (
                  <p className="disease-guide-source-checked">
                    资料语言：{sourceLanguageLabels[selectedSource.language] ?? selectedSource.language}
                  </p>
                )}
                <p className="disease-guide-source-checked">核查日期：{selectedSource.checked_at}</p>
                {selectedSource.usage_note && (
                  <p className="disease-guide-source-usage">本指南使用它来：{selectedSource.usage_note}</p>
                )}
                <a className="disease-guide-source-link" href={selectedSource.url} target="_blank" rel="noreferrer">
                  打开原始来源 <ExternalLink size={14} />
                </a>
              </aside>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function GuidePoint({
  point,
  sources,
  onOpenSource,
}: {
  point: DiseaseGuidePoint;
  sources: DiseaseGuideSource[];
  onOpenSource: (sourceId: string, trigger: HTMLButtonElement) => void;
}) {
  const researchContext = point.research_context;
  const contextSourceIds = new Set(
    researchContext
      ? [
          researchContext.goal,
          researchContext.current,
          researchContext.unknown,
        ].flatMap((claim) => claim.source_ids)
      : [],
  );
  const footerSourceIds = researchContext
    ? point.source_ids.filter((id) => !contextSourceIds.has(id))
    : point.source_ids;

  return (
    <article className="disease-guide-point">
      {(point.evidence_status !== "established" || Boolean(point.region)) && (
        <div className="disease-guide-point-heading">
          <span className={`disease-guide-evidence-status ${point.evidence_status}`}>
            {evidenceLabels[point.evidence_status]}
          </span>
          {point.evidence_stage && <span className="disease-guide-stage">{point.evidence_stage}</span>}
          {point.region && <span className="disease-guide-stage">{point.region}</span>}
          {researchContext && (
            <span className="disease-guide-stage">
              {researchEvidenceLabels[researchContext.evidence_kind]}
            </span>
          )}
        </div>
      )}
      {point.question && (
        <h4 className="disease-guide-point-question">{point.question}</h4>
      )}
      {researchContext ? (
        <div className="disease-guide-research-body">
          {researchContext.title && (
            <h4 className="disease-guide-research-title">{researchContext.title}</h4>
          )}
          <ResearchClaim title="想解决什么问题" claim={researchContext.goal} sources={sources} onOpen={onOpenSource} />
          <ResearchClaim title="目前进展" claim={researchContext.current} sources={sources} onOpen={onOpenSource} />
          <ResearchClaim title="还有哪些不确定" claim={researchContext.unknown} sources={sources} onOpen={onOpenSource} />
        </div>
      ) : (
        <div className="disease-guide-point-content">
          <p className="disease-guide-point-answer">{point.text}</p>
          {point.explanation && (
            <p className="disease-guide-point-explanation">{point.explanation.text}</p>
          )}
        </div>
      )}
      {point.qualifier && <small>{point.qualifier}</small>}
      {footerSourceIds.length > 0 && (
        <SourceLinks sourceIds={footerSourceIds} sources={sources} onOpen={onOpenSource} />
      )}
    </article>
  );
}

function ResearchClaim({
  title,
  claim,
  sources,
  onOpen,
}: {
  title: string;
  claim: { text: string; source_ids: string[] };
  sources: DiseaseGuideSource[];
  onOpen: (sourceId: string, trigger: HTMLButtonElement) => void;
}) {
  return (
    <div className="disease-guide-context-row">
      <h4>{title}</h4>
      <p>{claim.text}</p>
      <SourceLinks sourceIds={claim.source_ids} sources={sources} onOpen={onOpen} />
    </div>
  );
}

function termSourceIds(term: DiseaseGuideTerm) {
  return [...new Set([
    ...term.definition.source_ids,
    ...(term.context?.source_ids ?? []),
  ])];
}

function SourceLinks({
  sourceIds,
  sources,
  onOpen,
}: {
  sourceIds: string[];
  sources: DiseaseGuideSource[];
  onOpen: (sourceId: string, trigger: HTMLButtonElement) => void;
}) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  return (
    <div className="disease-guide-source-links" aria-label="引用来源">
      <span>依据</span>
      {sourceIds.map((sourceId) => (
        (() => {
          const index = sources.findIndex((source) => source.id === sourceId);
          const source = sourceById.get(sourceId);
          if (!source || index < 0) return null;

          return (
            <button
              type="button"
              key={sourceId}
              title={source.title}
              aria-label={`查看依据 ${index + 1}：${source.organization} · ${source.title}`}
              onClick={(event) => onOpen(sourceId, event.currentTarget)}
            >
              [{index + 1}]
            </button>
          );
        })()
      ))}
    </div>
  );
}

export default DiseaseGuidePage;
