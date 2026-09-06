"""Check generated text for a few unsafe medical claims."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.medical.ai.models import MedicalInsightReport


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
    r"(?:患者|病人)",
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
    r"|\byou\s+(?:should|must|need\s+to|are\s+advised\s+to)\s+"
    r"(?:seek|go\s+to|call|contact)\s+(?:emergency|urgent|"
    r"the\s+emergency\s+department|emergency\s+services|911)\b"
    r"|\b(?:seek|go\s+to|call)\s+(?:emergency|urgent|"
    r"the\s+emergency\s+department|emergency\s+services|911)\b"
    r"|(?:你|您)\s*(?:应该|需要|必须|请|建议|不要|不可|切勿|请勿)?\s*"
    r"(?:立即|马上|立刻)?\s*(?:就医|去急诊|联系急救|拨打急救|呼叫急救)",
    re.I,
)


def validate_safety(report: MedicalInsightReport) -> SafetyValidation:
    """Reject direct diagnosis and treatment instructions before persistence."""
    text = _report_text(report)
    errors: list[str] = []
    if _PERSONAL_DIAGNOSIS.search(text):
        errors.append("report contains a personalized diagnosis")
    if _TREATMENT_COMMAND.search(text):
        errors.append("report contains a treatment or medication instruction")
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
        *(term.term for term in report.medical_terms),
        *(term.explanation for term in report.medical_terms),
        *report.questions_for_professional,
        *report.warnings,
    ]
    return "\n".join(parts)
