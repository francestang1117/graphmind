import { ArrowLeft, BookOpen, ExternalLink, Search, ShieldCheck, Upload, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useDiseaseGuide, useDiseaseGuideSearch } from "../hooks/useDiseaseGuide";
import type { DiseaseGuidePoint, DiseaseGuideSearchItem, DiseaseGuideSource } from "../services/api";

interface DiseaseGuidePageProps {
  onOpenMySources: () => void;
  onOpenResearch: () => void;
}

const FABRY_CONCEPT_ID = "mesh:D000795";

const evidenceLabels: Record<DiseaseGuidePoint["evidence_status"], string> = {
  established: "已有认识",
  clinical_research: "临床研究",
  early_exploration: "早期探索",
};

function DiseaseGuidePage({ onOpenMySources, onOpenResearch }: DiseaseGuidePageProps) {
  const [query, setQuery] = useState("");
  const [selectedConcept, setSelectedConcept] = useState<DiseaseGuideSearchItem | null>(null);
  const [openSourceId, setOpenSourceId] = useState<string | null>(null);
  const [region, setRegion] = useState("JP");
  const searchQuery = useDiseaseGuideSearch(query);
  const guideQuery = useDiseaseGuide(
    selectedConcept?.guide_status === "available" ? selectedConcept.concept_id : null,
    "zh-CN",
    region,
  );
  const selectedSource = useMemo<DiseaseGuideSource | null>(() => {
    if (!guideQuery.data || !openSourceId) return null;
    return guideQuery.data.sources.find((source) => source.id === openSourceId) ?? null;
  }, [guideQuery.data, openSourceId]);

  const openFabryGuide = () => {
    setSelectedConcept({
      concept_id: FABRY_CONCEPT_ID,
      preferred_name_en: "Fabry disease",
      preferred_name_zh: "法布雷病",
      matched_alias: "法布雷病",
      guide_status: "available",
      guide_languages: ["zh-CN"],
    });
    setOpenSourceId(null);
    setRegion("JP");
  };

  const selectConcept = (concept: DiseaseGuideSearchItem) => {
    setSelectedConcept(concept);
    setOpenSourceId(null);
    setRegion("JP");
  };

  if (!selectedConcept) {
    return (
      <div className="disease-guide-page">
        <section className="disease-guide-search-hero" aria-labelledby="disease-guide-title">
          <span className="disease-guide-eyebrow">疾病探索</span>
          <h2 id="disease-guide-title">你想了解什么疾病？</h2>
          <p>先从一份经过来源核对的通俗概览开始，再决定要不要查看论文和研究依据。</p>
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
            <span>示例指南</span>
            <button type="button" onClick={openFabryGuide}>法布雷病 Fabry disease</button>
          </div>
        </section>
        <section className="disease-guide-secondary-entry" aria-label="其他入口">
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
          <ArrowLeft size={16} /> 返回搜索
        </button>
        <section className="disease-guide-empty-state">
          <BookOpen size={30} />
          <h2>{selectedConcept.preferred_name_zh || selectedConcept.preferred_name_en}</h2>
          <p>我们已识别这个疾病概念，但公共指南正在准备中。现在可以先使用研究工具查看自己的资料。</p>
          <button type="button" className="disease-guide-primary-action" onClick={onOpenResearch}>打开研究工具</button>
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
            <span className="disease-guide-eyebrow">疾病指南 · {guideQuery.data.preferred_name_en}</span>
            <h2>{guideQuery.data.title}</h2>
            <p>先了解基本概念、可能影响和治疗方向，再进入研究依据查看论文与原文。</p>
            <div className="disease-guide-meta">
              <span><ShieldCheck size={14} /> 内容核查至 {guideQuery.data.reviewed_at}</span>
              <span className={guideQuery.data.region_status === "verified" ? "verified" : "unverified"}>
                {guideQuery.data.region_status === "verified" ? "日本资料已核对" : "当地监管状态未核对"}
              </span>
              <label className="disease-guide-region-picker">
                <span>地区</span>
                <select value={region} onChange={(event) => setRegion(event.target.value)}>
                  <option value="JP">日本</option>
                  <option value="US">美国</option>
                  <option value="EU">欧盟/其他</option>
                </select>
              </label>
            </div>
            {guideQuery.data.region_status === "not_verified" && (
              <p className="disease-guide-region-note">{guideQuery.data.region_note}</p>
            )}
          </header>

          <section className="disease-guide-overview" aria-labelledby="disease-guide-overview-title">
            <span className="disease-guide-section-kicker">先看这里</span>
            <h3 id="disease-guide-overview-title">一句话认识</h3>
            <p>{guideQuery.data.overview.text}</p>
            <SourceLinks
              sourceIds={guideQuery.data.overview.source_ids}
              sources={guideQuery.data.sources}
              onOpen={setOpenSourceId}
            />
          </section>

          <section className="disease-guide-topics" aria-labelledby="disease-guide-topics-title">
            <div className="disease-guide-section-heading">
              <div>
                <span className="disease-guide-section-kicker">继续探索</span>
                <h3 id="disease-guide-topics-title">你可能还想知道</h3>
              </div>
              <span className="disease-guide-topic-count">{guideQuery.data.topics.length} 个主题</span>
            </div>
            {guideQuery.data.topics.map((topic) => (
              <details className="disease-guide-topic" key={topic.id} open={topic.id === "what_is"}>
                <summary>
                  <span>
                    <strong>{topic.title}</strong>
                    <small>{topic.question}</small>
                  </span>
                  <span className="disease-guide-summary-marker" aria-hidden="true">＋</span>
                </summary>
                <div className="disease-guide-topic-body">
                  <p className="disease-guide-topic-summary">{topic.summary.text}</p>
                  <SourceLinks
                    sourceIds={topic.summary.source_ids}
                    sources={guideQuery.data.sources}
                    onOpen={setOpenSourceId}
                  />
                  <div className="disease-guide-points">
                    {topic.key_points.map((point) => (
                      <GuidePoint
                        key={point.id}
                        point={point}
                        sources={guideQuery.data.sources}
                        onOpenSource={setOpenSourceId}
                      />
                    ))}
                  </div>
                </div>
              </details>
            ))}
          </section>

          <section className="disease-guide-next-step">
            <div>
              <span className="disease-guide-section-kicker">下一步</span>
              <h3>想核对论文和原文？</h3>
              <p>研究依据会把具体论文、研究对象和可定位的原文放在一起；它与这份公共指南分开管理。</p>
            </div>
            <div className="disease-guide-next-actions">
              <button type="button" className="disease-guide-primary-action" onClick={onOpenResearch}>
                <BookOpen size={16} /> 查看研究依据
              </button>
              <button type="button" className="disease-guide-secondary-action" onClick={onOpenMySources}>
                <Upload size={16} /> 上传自己的资料
              </button>
            </div>
          </section>

          {selectedSource && (
            <div className="disease-guide-source-backdrop" role="presentation" onClick={() => setOpenSourceId(null)}>
              <aside
                className="disease-guide-source-drawer"
                role="dialog"
                aria-modal="true"
                aria-labelledby="disease-guide-source-title"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="disease-guide-source-heading">
                  <div>
                    <span className="disease-guide-section-kicker">来源</span>
                    <h3 id="disease-guide-source-title">{selectedSource.title}</h3>
                  </div>
                  <button type="button" className="disease-guide-icon-button" aria-label="关闭来源" onClick={() => setOpenSourceId(null)}>
                    <X size={18} />
                  </button>
                </div>
                <p className="disease-guide-source-organization">{selectedSource.organization}</p>
                <p className="disease-guide-source-checked">核查日期：{selectedSource.checked_at}</p>
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
  onOpenSource: (sourceId: string) => void;
}) {
  return (
    <article className="disease-guide-point">
      <div className="disease-guide-point-heading">
        <span className={`disease-guide-evidence-status ${point.evidence_status}`}>
          {evidenceLabels[point.evidence_status]}
        </span>
        {point.evidence_stage && <span className="disease-guide-stage">{point.evidence_stage}</span>}
        {point.region && <span className="disease-guide-stage">{point.region}</span>}
      </div>
      <p>{point.text}</p>
      {point.qualifier && <small>{point.qualifier}</small>}
      <SourceLinks sourceIds={point.source_ids} sources={sources} onOpen={onOpenSource} />
    </article>
  );
}

function SourceLinks({
  sourceIds,
  sources,
  onOpen,
}: {
  sourceIds: string[];
  sources: DiseaseGuideSource[];
  onOpen: (sourceId: string) => void;
}) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  return (
    <div className="disease-guide-source-links" aria-label="引用来源">
      {sourceIds.map((sourceId) => (
        <button
          type="button"
          key={sourceId}
          aria-label={`查看来源 · ${sourceById.get(sourceId)?.organization ?? sourceId}`}
          onClick={() => onOpen(sourceId)}
        >
          查看来源 · {sourceById.get(sourceId)?.organization ?? sourceId}
        </button>
      ))}
    </div>
  );
}

export default DiseaseGuidePage;
