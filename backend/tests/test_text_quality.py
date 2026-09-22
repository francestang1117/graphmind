from app.services.medical.text_quality import assess_passage


def test_quality_gate_rejects_damaged_column_fragment():
    result = assess_passage("ary Gb3 isoforms were higher in the selected cohort.", section_type="results")

    assert not result.usable
    assert "obvious_column_interleave" in result.reasons


def test_quality_gate_rejects_non_medical_and_reference_passages():
    for section_type in ("references", "acknowledgements", "funding"):
        result = assess_passage("Smith J. 2020; 12:34. Additional metadata.", section_type=section_type)
        assert not result.usable
        assert "non_medical_section" in result.reasons


def test_quality_gate_allows_a_real_short_cjk_population_sentence():
    result = assess_passage("研究纳入成年人。", section_type="population")

    assert result.usable
    assert result.score > 0


def test_quality_gate_requires_two_soft_signals_to_reject():
    result = assess_passage(
        "The study reported a result without a final sentence and the outcome remained unclear"
    )

    assert result.usable
    assert "no_sentence_boundary" in result.reasons
