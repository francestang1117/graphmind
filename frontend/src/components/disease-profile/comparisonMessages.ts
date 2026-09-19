import type {
  ComparisonCoverageStatus,
  ComparisonLanguage,
  ComparisonSupportStatus,
} from "../../services/api";

export type ComparisonMethodKey =
  | "design"
  | "population"
  | "human_animal_in_vitro"
  | "sample_size"
  | "comparator";

export interface ComparisonMessages {
  eyebrow: string;
  title: string;
  description: string;
  sourceCount: (count: number) => string;
  compareEyebrow: string;
  selectedCount: (count: number) => string;
  languageLabel: string;
  compare: string;
  comparing: string;
  methods: string;
  findings: string;
  limitations: string;
  questions: string;
  noCitedItems: string;
  methodLabels: Record<ComparisonMethodKey, string>;
  supportStatus: Record<ComparisonSupportStatus, string>;
  coverageStatus: Record<ComparisonCoverageStatus, string>;
  notReportedValue: string;
  sourceUnavailableValue: string;
  chunks: (selected: number, total: number) => string;
  findingsTruncated: (shown: number, total: number) => string;
  limitationsTruncated: (shown: number, total: number) => string;
  warning: (code: string) => string;
  viewEvidence: (count: number) => string;
  evidenceNavigation: string;
  evidencePosition: (index: number, total: number) => string;
  previousEvidence: string;
  nextEvidence: string;
  closeEvidence: string;
  evidenceSource: string;
  evidenceId: (id: string) => string;
  runId: (id: string) => string;
  page: (start: number, end?: number | null) => string;
  openSource: string;
  excerptWarning: string;
  languageNotice: string;
}

const MESSAGES: Record<ComparisonLanguage, ComparisonMessages> = {
  en: {
    eyebrow: "Evidence comparison",
    title: "Compare selected sources",
    description: "Methods, reported findings, and limitations are shown per document. No overall ranking is generated.",
    sourceCount: (count) => `${count} sources`,
    compareEyebrow: "Compare sources",
    selectedCount: (count) => `${count}/5 selected`,
    languageLabel: "Output language",
    compare: "Compare selected documents",
    comparing: "Comparing...",
    methods: "Study methods",
    findings: "Reported findings",
    limitations: "Limitations",
    questions: "Questions to discuss with a clinician",
    noCitedItems: "No cited items available.",
    methodLabels: {
      design: "Study design",
      population: "Population",
      human_animal_in_vitro: "Human / animal / in vitro",
      sample_size: "Sample size",
      comparator: "Comparator",
    },
    supportStatus: {
      supported: "Supported",
      partially_supported: "Partially supported",
      not_reported: "Not reported",
      uncertain: "Uncertain",
      source_unavailable: "Source unavailable",
    },
    coverageStatus: {
      complete: "Coverage complete",
      partial: "Coverage partial",
      unknown: "Coverage unknown",
    },
    notReportedValue: "Not reported in the selected source evidence.",
    sourceUnavailableValue: "This field could not be traced to an available source.",
    chunks: (selected, total) => `${selected}/${total} chunks`,
    findingsTruncated: (shown, total) => `Showing ${shown} of ${total} findings. Open the single-document report for the remaining items.`,
    limitationsTruncated: (shown, total) => `Showing ${shown} of ${total} limitations. Open the single-document report for the remaining items.`,
    warning: (code) => code === "comparison_coverage_partial"
      ? "Some source sections were not included in this comparison."
      : "Source coverage could not be confirmed for this comparison.",
    viewEvidence: (count) => `View evidence (${count})`,
    evidenceNavigation: "Comparison evidence navigation",
    evidencePosition: (index, total) => `Evidence ${index} / ${total}`,
    previousEvidence: "Previous evidence",
    nextEvidence: "Next evidence",
    closeEvidence: "Close comparison evidence",
    evidenceSource: "Comparison evidence source",
    evidenceId: (id) => `Evidence ${id}`,
    runId: (id) => `Run ${id}`,
    page: (start, end) => `Page ${start}${end && end !== start ? `-${end}` : ""}`,
    openSource: "Open source document",
    excerptWarning: "Excerpt shortened for preview. Open the source document to read the full passage.",
    languageNotice: "Fixed labels and clinician question templates follow the selected language. Findings and quotations remain in the source language.",
  },
  zh: {
    eyebrow: "证据对照",
    title: "对照所选资料",
    description: "按文档分别显示研究方法、报告发现和局限，不生成总体排名。",
    sourceCount: (count) => `${count} 份资料`,
    compareEyebrow: "对照资料",
    selectedCount: (count) => `已选择 ${count}/5 份`,
    languageLabel: "输出语言",
    compare: "对照所选文档",
    comparing: "正在对照……",
    methods: "研究方法",
    findings: "报告的发现",
    limitations: "研究局限",
    questions: "可以和医生讨论的问题",
    noCitedItems: "没有可引用的条目。",
    methodLabels: {
      design: "研究设计",
      population: "研究人群",
      human_animal_in_vitro: "人体 / 动物 / 体外",
      sample_size: "样本量",
      comparator: "对照组",
    },
    supportStatus: {
      supported: "有来源支持",
      partially_supported: "部分支持",
      not_reported: "未报告",
      uncertain: "支持情况不确定",
      source_unavailable: "来源不可用",
    },
    coverageStatus: {
      complete: "覆盖完整",
      partial: "覆盖不完整",
      unknown: "覆盖情况未知",
    },
    notReportedValue: "所选来源证据未报告此字段。",
    sourceUnavailableValue: "当前无法将此字段追溯到可用来源。",
    chunks: (selected, total) => `已纳入 ${selected}/${total} 个文本块`,
    findingsTruncated: (shown, total) => `当前显示 ${shown}/${total} 条发现。其余内容请打开单篇文档报告查看。`,
    limitationsTruncated: (shown, total) => `当前显示 ${shown}/${total} 条局限。其余内容请打开单篇文档报告查看。`,
    warning: (code) => code === "comparison_coverage_partial"
      ? "本次对照没有纳入部分来源章节。"
      : "本次对照无法确认来源覆盖范围。",
    viewEvidence: (count) => `查看出处（${count}）`,
    evidenceNavigation: "对照证据导航",
    evidencePosition: (index, total) => `第 ${index}/${total} 条出处`,
    previousEvidence: "上一条出处",
    nextEvidence: "下一条出处",
    closeEvidence: "关闭对照证据",
    evidenceSource: "对照证据",
    evidenceId: (id) => `证据 ${id}`,
    runId: (id) => `运行 ${id}`,
    page: (start, end) => `第 ${start}${end && end !== start ? `-${end}` : ""} 页`,
    openSource: "打开原文",
    excerptWarning: "当前为引文节选。请打开原文查看完整段落。",
    languageNotice: "固定标签和医生讨论问题会随所选语言变化；研究发现和原文引文保留资料原语言。",
  },
  ja: {
    eyebrow: "エビデンス比較",
    title: "選択した資料を比較",
    description: "研究方法、報告された所見、限界を文書ごとに示します。全体の順位付けは行いません。",
    sourceCount: (count) => `${count}件の資料`,
    compareEyebrow: "資料を比較",
    selectedCount: (count) => `${count}/5件を選択`,
    languageLabel: "表示言語",
    compare: "選択した文書を比較",
    comparing: "比較中…",
    methods: "研究方法",
    findings: "報告された所見",
    limitations: "研究の限界",
    questions: "医療者と相談する質問",
    noCitedItems: "引用できる項目はありません。",
    methodLabels: {
      design: "研究デザイン",
      population: "研究対象",
      human_animal_in_vitro: "ヒト / 動物 / in vitro",
      sample_size: "サンプル数",
      comparator: "比較対象",
    },
    supportStatus: {
      supported: "根拠あり",
      partially_supported: "一部の根拠あり",
      not_reported: "未報告",
      uncertain: "根拠が不確実",
      source_unavailable: "出典を利用できません",
    },
    coverageStatus: {
      complete: "網羅的",
      partial: "一部のみ",
      unknown: "範囲不明",
    },
    notReportedValue: "選択した出典ではこの項目は報告されていません。",
    sourceUnavailableValue: "この項目を利用可能な出典に追跡できません。",
    chunks: (selected, total) => `${selected}/${total}チャンク`,
    findingsTruncated: (shown, total) => `${shown}/${total}件の所見を表示しています。残りは単一文書のレポートで確認してください。`,
    limitationsTruncated: (shown, total) => `${shown}/${total}件の限界を表示しています。残りは単一文書のレポートで確認してください。`,
    warning: (code) => code === "comparison_coverage_partial"
      ? "一部の出典セクションが比較に含まれていません。"
      : "この比較の出典範囲を確認できませんでした。",
    viewEvidence: (count) => `出典を見る（${count}）`,
    evidenceNavigation: "比較エビデンスの移動",
    evidencePosition: (index, total) => `出典 ${index} / ${total}`,
    previousEvidence: "前の出典",
    nextEvidence: "次の出典",
    closeEvidence: "比較エビデンスを閉じる",
    evidenceSource: "比較エビデンス",
    evidenceId: (id) => `証拠 ${id}`,
    runId: (id) => `実行 ${id}`,
    page: (start, end) => `${start}${end && end !== start ? `-${end}` : ""}ページ`,
    openSource: "原文を開く",
    excerptWarning: "これは抜粋表示です。全文は原文を開いて確認してください。",
    languageNotice: "固定ラベルと医療者向け質問は選択言語で表示します。所見と引用は出典の言語で保持します。",
  },
};

export function getComparisonMessages(language: ComparisonLanguage): ComparisonMessages {
  return MESSAGES[language] ?? MESSAGES.en;
}
