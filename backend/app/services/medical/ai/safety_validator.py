"""Check generated text for a few unsafe medical claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.medical.ai.models import MedicalInsightReport
from app.services.medical.ai.question_templates import is_controlled_question


@dataclass
class SafetyValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=lambda: ["not_medical_advice"])


_PERSONAL_DIAGNOSIS = re.compile(
    r"\b(?:you have|you likely have|you may have|you could have|"
    r"you seem to have|you appear to have|you've got|this proves you have|"
    r"this means you have|this suggests you have|diagnose you|"
    r"you are suffering from)\b"
    r"|\b(?:you|your report)\s+(?:are|is)\s+diagnosed\s+with\b"
    r"|(?:你|您)\s*(?:可能|很可能|疑似|已经|患有|患了|得了|患上|被诊断为|被诊断出|有)\s*"
    r"(?:[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\s-]{0,30}?"
    r"(?:病|症|炎|癌|感染|疾病|病情|综合征)|疾病|病情|感染|确诊)"
    r"|(?:你|您)\s*(?:是|属于)\s*[\u4e00-\u9fffA-Za-z0-9\s-]{0,20}"
    r"(?:患者|病人)"
    r"|(?:我|本人)\s*(?:可能|很可能|疑似|是不是|是否|已经|患有|患了|得了|患上|被诊断为|被诊断出|有)\s*"
    r"(?:[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\s-]{0,30}?"
    r"(?:病|症|炎|癌|感染|疾病|病情|综合征)|疾病|病情|感染|确诊)"
    r"|\b(?:does|do)\s+(?:this|that|the report|these results?)\s+"
    r"(?:prove|show|mean|confirm)\s+(?:that\s+)?I\s+"
    r"(?:have|got|suffer from|am diagnosed with)\b"
    r"|\b(?:do|could|might|may)\s+I\s+(?:have|be suffering from)\s+"
    r"(?:(?:this|that|a|an|the)\s+)?"
    r"(?:disease|condition|illness|cancer|infection|syndrome)\b"
    r"|\bI\s+(?:(?:likely|may|could|seem to|appear to)\s+)?have\s+"
    r"(?:(?:this|that|a|an|the)\s+)?"
    r"(?:disease|condition|illness|cancer|infection|syndrome)\b"
    r"|\bI\s+(?:am|was)\s+diagnosed\s+with\b"
    r"|\bI\s+am\s+suffering\s+from\b",
    re.I,
)
_TREATMENT_COMMAND = re.compile(
    r"\byou\s+(?:should|must|need\s+to|are\s+advised\s+to)\s+"
    r"(?:not\s+|never\s+)?"
    r"(?:(?:stop|start|change|adjust|increase|decrease|take|use|avoid)\s+)?"
    r"(?:(?:your|the)\s+)?(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|\b(?:stop|start|change|adjust|increase|decrease)\s+"
    r"(?:taking\s+)?(?:(?:your|the)\s+)?"
    r"(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|\b(?:take|use|administer)\s+(?:(?:your|the)\s+)?"
    r"(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|\b(?:take|use|administer)\s+\d+(?:\.\d+)?\s*"
    r"(?:mg|mcg|g|ml|mL|tablets?|capsules?)\b"
    r"|\b(?:do not|don't|never)\s+"
    r"(?:stop|start|change|adjust|increase|decrease|take|use|avoid)\s+"
    r"(?:(?:your|the)\s+)?(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|(?:你|您)\s*(?:应该|需要|必须|请|建议你|建议|自行|不要|不可|切勿|请勿|不得)?\s*"
    r"(?:立即|自行)?\s*"
    r"(?:停药|停用(?:药物|药)|开始(?:用药|服药)|换药|调整剂量|增加剂量|减少剂量|"
    r"加大剂量|减量|服用|使用|加药|减药)"
    r"|(?:建议|请|应当|应该|必须|不要|不可|切勿|请勿|不得|禁止)\s*(?:你|您)?\s*"
    r"(?:自行\s*)?"
    r"(?:停药|停用(?:药物|药)|开始(?:用药|服药)|换药|调整剂量|增加剂量|减少剂量|"
    r"加大剂量|减量|服用|使用|加药|减药)"
    r"|(?:停用|增加|减少|调整|加大|减小)\s*(?:药物|药量|剂量)"
    r"|(?:服用|使用|口服|注射|给予)\s*\d+(?:\.\d+)?\s*"
    r"(?:mg|mcg|g|ml|mL|毫克|微克|克|毫升|片|粒)"
    r"|\b(?:should|must|can|may)\s+I\s+(?:not\s+)?"
    r"(?:stop|start|change|adjust|increase|decrease|take|use|avoid)\s+"
    r"(?:taking\s+)?(?:(?:my|your|the|this|that)\s+)?"
    r"(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|\b(?:should|must|can|may)\s+I\s+(?:take|use|administer)\s+"
    r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|mL|tablets?|capsules?)\b"
    r"|(?:我|本人)\s*(?:应该|需要|必须|是否可以|能否|可以|可不可以|要不要)?\s*"
    r"(?:立即|马上|立刻|每天|每日|一次)?\s*"
    r"(?:停药|停用(?:药物|药)|开始(?:用药|服药|服用)|换药|调整剂量|增加剂量|减少剂量|"
    r"加大剂量|减量|服用|使用|加药|减药)"
    r"|(?:我|本人)\s*(?:每天|每日|一次)?\s*"
    r"(?:应该|需要|可以|是否可以|能否|可不可以|要不要)?\s*"
    r"(?:服用|使用|口服|注射|给予)\s*(?:多少|几)\s*"
    r"(?:mg|mcg|g|ml|mL|毫克|微克|克|毫升|片|粒)"
    r"|(?:我|本人)\s*(?:应该|需要|必须|是否可以|是否应该|能否|可以|可不可以|要不要)?\s*"
    r"(?:换成|改用|改为|替换为)\s*(?:论文|研究|文献|文章)[^。！？?!]{0,30}"
    r"(?:药物|药|治疗|疗法)"
    r"|(?:我|本人)\s*(?:怎样|如何)才能\s*(?:立即|马上|立刻)?\s*"
    r"(?:使用|服用|开始(?:用药|服药|服用))\s*(?:这种|该|这个)?"
    r"(?:实验|试验)?(?:药物|药|治疗|疗法)"
    r"|(?:既然|因为)[^。！？?!]{0,40}(?:有效|成功)[^。！？?!]{0,30}"
    r"(?:我|本人)[^。！？?!]{0,20}(?:一定|肯定|必然|也会)[^。！？?!]{0,20}"
    r"(?:有效|受益|改善|好转|适合)"
    r"|\b(?:how much|how many)\s+(?:medication|medicine|drug|dosage|dose)\s+"
    r"(?:should|must|can|may)\s+I\s+(?:take|use|administer)\b"
    r"|\b(?:do I need to|can I|may I)\s+(?:stop|start|change|adjust|increase|"
    r"decrease|take|use|avoid)\s+(?:taking\s+)?(?:(?:my|your|the|this|that)\s+)?"
    r"(?:medication|medicine|dose|dosage|treatment|drug|prescription)\b"
    r"|\byou\s+(?:should|must|need\s+to|are\s+advised\s+to)\s+"
    r"(?:seek|go\s+to|call|contact)\s+(?:emergency|urgent|"
    r"the\s+emergency\s+department|emergency\s+services|911)\b"
    r"|\b(?:seek|go\s+to|call)\s+(?:emergency|urgent|"
    r"the\s+emergency\s+department|emergency\s+services|911)\b"
    r"|(?:你|您)\s*(?:应该|需要|必须|请|建议|不要|不可|切勿|请勿)?\s*"
    r"(?:立即|马上|立刻)?\s*(?:就医|去急诊|联系急救|拨打急救|呼叫急救)",
    re.I,
)

_PERSONAL_QUESTION_MARKER = re.compile(
    r"\b(?:for|to)\s+(?:me|people\s+like\s+me|people\s+with\s+my\s+condition|"
    r"my\s+(?:case|condition|situation))\b"
    r"|\bin\s+my\s+(?:case|condition|situation)\b"
    r"|\bpeople\s+(?:like\s+me|with\s+my\s+condition)\b"
    r"|\b(?:help|benefit|work)\s+(?:me|people\s+like\s+me|"
    r"people\s+with\s+my\s+condition)\b"
    r"|\bmy\s+(?:treatment|medication|medicine|dose|dosage|drug|therapy|"
    r"prescription|condition|case|situation|symptom(?:s)?)\b"
    r"|(?:给我|为我|对我|适合我|合适我|更适合我|最适合我|适用于我|"
    r"对我合适|对我有效|对我安全|对我有用|适合我的情况|适合我的病情|"
    r"对我的情况合适|对我的病情有效|像我这样的人|类似人群|"
    r"我的(?:治疗|用药|药物|剂量|情况|病情|症状))",
    re.I,
)
_PERSONAL_TREATMENT_ACTION = re.compile(
    r"\b(?:should|must|can|could|may|would)\s+i\s+"
    r"(?:take|use|start|stop|switch|change|try|choose|increase|decrease|adjust|"
    r"continue)\b"
    r"|\bwhat\s+(?:should|can|may|would)\s+i\s+"
    r"(?:take|use|start|stop|switch|change|try|choose|increase|decrease|adjust)\b"
    r"|\b(?:should|must|can|could|may|would)\s+(?:my\s+)?doctor\b"
    r"[^?？!！\n]{0,80}\b(?:prescribe|recommend|give|start|switch|change|"
    r"put\s+me\s+on)\b"
    r"|\b(?:should|must|can|could|may|would)\s+my\s+"
    r"(?:treatment|medication|medicine|dose|dosage|drug|therapy|prescription)\s+"
    r"(?:be\s+)?(?:switched|changed|adjusted|replaced|started|stopped)\b"
    r"|(?:该|应该|需要|可以|能否|是否应该|要不要)\s*(?:选|选择|选用)\s*"
    r"(?:哪种|什么)?\s*(?:药物|药|治疗|疗法)"
    r"|(?:医生|大夫)[^。！？?!]{0,20}(?:给我开|开给我|为我开|处方|"
    r"推荐给我|帮我换药)",
    re.I,
)
_RESEARCH_APPLICABILITY_QUESTION = re.compile(
    r"^\s*(?:are|is|could|would|might|may|can)\s+"
    r"(?:(?:these|the|this)\s+)?(?:findings|results|evidence|study|research|"
    r"population|data)(?:\s+population)?"
    r"(?:\s+(?:from|in)\s+(?:this|the)\s+study)?\s+"
    r"(?:apply|appropriate|suitable|relevant|comparable|"
    r"applicable|be\s+(?:appropriate|suitable|relevant|comparable|applicable))\s+"
    r"(?:to|for)\s+(?:people\s+like\s+me|people\s+with\s+my\s+condition|"
    r"my\s+(?:condition|case|situation)|me)\s*[?？!！。\.]*\s*$",
    re.I,
)
_RESEARCH_APPLICABILITY_HELP = re.compile(
    r"^\s*(?:could|would|might|may|can)\s+"
    r"(?:(?:these|the|this)\s+)?(?:findings|results|evidence|study|research|data)"
    r"(?:\s+(?:from|in)\s+(?:this|the)\s+study)?\s+"
    r"(?:help|benefit)\s+(?:me|people\s+like\s+me|people\s+with\s+my\s+condition)"
    r"\s*[?？!！。\.]*\s*$",
    re.I,
)
_RESEARCH_REPORTING_QUESTION = re.compile(
    r"^\s*(?:what|which|how)\b[^?？!！\n]{0,100}\b(?:did|does|do)\s+"
    r"(?:the\s+)?(?:study|paper|research|authors?|investigators?)\b"
    r"[^?？!！\n]{0,100}\b(?:report|find|observe|include|measure|show)\b"
    r"[^?？!！\n]{0,100}(?:for|about|in)\s+"
    r"(?:people\s+like\s+me|people\s+with\s+my\s+condition|"
    r"my\s+(?:condition|case|situation))\s*[?？!！。\.]*\s*$",
    re.I,
)
_RESEARCH_CJK_APPLICABILITY = re.compile(
    r"^\s*(?:"
    r"(?:这些(?:发现|结果)|(?:这项|该)研究|研究(?:结果|证据|人群)|该证据)"
    r"[^。！？?!]{0,30}(?:适用于|推广到|适合)"
    r"[^。！？?!]{0,20}(?:我的情况|我的病情|类似人群|我)"
    r"|"
    r"(?:这些(?:发现|结果)|(?:这项|该)研究|研究(?:结果|证据|人群)|该证据)"
    r"[^。！？?!]{0,20}(?:我的情况|我的病情|类似人群|我)"
    r"[^。！？?!]{0,20}(?:具有可比性|可比)"
    r")\s*[?？!！。\.]*\s*$",
    re.I,
)
_CJK_TREATMENT_TARGET = re.compile(
    r"(?:药物|药|剂量|治疗|疗法|用药|处方|换药|服用|使用)",
    re.I,
)
_PERSONALIZED_TREATMENT_BENEFIT = re.compile(
    r"\b(?:would|could|might|may|does)\s+"
    r"(?!(?:these|the)\s+(?:findings|results|evidence|study|research|paper|"
    r"population|data)\b)"
    r"(?:[A-Za-z][A-Za-z0-9-]*\s+){0,6}"
    r"(?:help|benefit|work)\s+(?:for\s+)?me\b"
    r"|(?!(?:这些发现|这些结果|该研究|这项研究|研究结果|研究人群|该证据))"
    r"(?:[\u4e00-\u9fffA-Za-z0-9-]{2,80})\s*"
    r"(?:对我有效|对我有用|能帮我|会帮助我)",
    re.I,
)


def _is_research_scoped_question(value: str) -> bool:
    """Allow only explicit research-object questions with personal targets."""
    if _PERSONAL_TREATMENT_ACTION.search(value):
        return False
    if (
        _RESEARCH_APPLICABILITY_QUESTION.fullmatch(value)
        or _RESEARCH_APPLICABILITY_HELP.fullmatch(value)
        or _RESEARCH_REPORTING_QUESTION.fullmatch(value)
    ):
        return True
    return bool(
        _RESEARCH_CJK_APPLICABILITY.fullmatch(value)
        and not _CJK_TREATMENT_TARGET.search(value)
    )


def _has_personalized_treatment_question(value: str) -> bool:
    """Default-deny personal treatment targets unless research scope is explicit."""
    has_personal_target = _PERSONAL_QUESTION_MARKER.search(value)
    has_treatment_action = _PERSONAL_TREATMENT_ACTION.search(value)
    has_personal_benefit = _PERSONALIZED_TREATMENT_BENEFIT.search(value)
    if not has_personal_target and not has_treatment_action and not has_personal_benefit:
        return False
    return not _is_research_scoped_question(value)


def validate_safety(report: MedicalInsightReport) -> SafetyValidation:
    """Reject direct diagnosis and treatment instructions before persistence."""
    text = _report_text(report)
    errors: list[str] = []
    if _PERSONAL_DIAGNOSIS.search(text):
        errors.append("report contains a personalized diagnosis")
    if _TREATMENT_COMMAND.search(text):
        errors.append("report contains a treatment or medication instruction")
    for item in report.question_suggestions:
        if item.topic is not None:
            if not is_controlled_question(item, report.language):
                errors.append("question suggestions must use server-controlled templates")
        elif _has_personalized_treatment_question(item.question):
            errors.append("question suggestions contain personalized medication guidance")
    return SafetyValidation(valid=not errors, errors=errors)


def _report_text(report: MedicalInsightReport) -> str:
    parts = [
        report.overview.title,
        report.overview.summary,
        report.overview.study_type,
        *(item.statement for item in report.key_findings),
        *(item.plain_explanation for item in report.key_findings),
        *(item.statement for item in report.limitations),
        *(item.plain_explanation for item in report.limitations),
        *(item.statement for item in report.what_it_means),
        *(item.plain_explanation for item in report.what_it_means),
        *(item.statement for item in report.what_it_does_not_mean),
        *(item.plain_explanation for item in report.what_it_does_not_mean),
        *(item.statement for item in report.applicability),
        *(item.plain_explanation for item in report.applicability),
        *(item.statement for item in report.future_research),
        *(item.plain_explanation for item in report.future_research),
        *(item.value for item in (
            report.study_methods.design,
            report.study_methods.population,
            report.study_methods.what_was_measured,
            report.study_methods.human_animal_in_vitro,
            report.study_methods.sample_size,
            report.study_methods.comparator,
        )),
        *(term.term for term in report.medical_terms),
        *(term.explanation for term in report.medical_terms),
        *(item.question for item in report.question_suggestions),
        *(item.rationale for item in report.question_suggestions),
        *report.questions_for_professional,
        *report.warnings,
    ]
    return "\n".join(parts)
