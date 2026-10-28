import json

from ares.adapters.grounded_synthesis import _answer_style, _build_synthesis_input


def test_answer_style_respects_explicit_length_over_topic() -> None:
    assert _answer_style('Explain neuroplasticity briefly')['depth'] == 'brief'
    assert _answer_style('Give a detailed explanation of neuroplasticity')['depth'] == 'detailed'
    assert _answer_style('Explain neuroplasticity in detail but keep it short')['depth'] == 'brief'
    assert _answer_style('What is neuroplasticity?')['depth'] == 'balanced'
    assert _answer_style('Explain short-term plasticity in detail')['depth'] == 'detailed'


def test_both_writers_receive_explanation_contract() -> None:
    payload = json.loads(_build_synthesis_input('Explain neuroplasticity in detail', []))
    assert payload['ANSWER_STYLE']['depth'] == 'detailed'
    assert 'explanation' in payload['ANSWER_STYLE']['structure']
    assert 'sources' not in payload['ANSWER_STYLE']['structure'].lower()
