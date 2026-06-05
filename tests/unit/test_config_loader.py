"""
tests/unit/test_config_loader.py
==================================
Unit tests for the configuration loader.

Covers:
- _load_rules()  — config/rules.yaml structure and values
- _load_loan_rules() — config/loan_rules.yaml structure and values
- get_settings() — singleton, default values, and convenience properties
"""

import pytest
from config.settings import get_settings, _load_rules, _load_loan_rules


# ---------------------------------------------------------------------------
# _load_rules() — basic contract
# ---------------------------------------------------------------------------

def test_rules_yaml_loads_without_error():
    rules = _load_rules()
    assert isinstance(rules, dict)
    assert len(rules) > 0


def test_rules_has_required_top_level_keys():
    rules = _load_rules()
    for key in ["applicant", "credit_score", "income", "debt_to_income", "risk_score"]:
        assert key in rules, f"Missing top-level key: {key}"


def test_dti_auto_reject_above_is_numeric():
    rules = _load_rules()
    assert isinstance(rules["debt_to_income"]["auto_reject_above"], float)


def test_credit_score_bands_have_min_max():
    rules = _load_rules()
    for band_name, band in rules["credit_score"]["bands"].items():
        assert "min" in band and "max" in band, f"Band {band_name} missing min/max"


def test_get_settings_returns_singleton():
    assert get_settings() is get_settings()


# ---------------------------------------------------------------------------
# _load_rules() — applicant section
# ---------------------------------------------------------------------------

def test_applicant_min_age_is_18():
    assert _load_rules()["applicant"]["min_age"] == 18


def test_applicant_max_age_is_70():
    assert _load_rules()["applicant"]["max_age"] == 70


def test_applicant_employment_types_has_three_bands():
    bands = _load_rules()["applicant"]["employment_types"]
    for band in ("stable", "moderate", "unstable"):
        assert band in bands, f"Missing employment band: {band}"


def test_salaried_is_in_stable_employment_band():
    bands = _load_rules()["applicant"]["employment_types"]
    assert "salaried" in bands["stable"]


def test_government_is_in_stable_employment_band():
    bands = _load_rules()["applicant"]["employment_types"]
    assert "government" in bands["stable"]


def test_employment_income_floors_are_positive_integers():
    floors = _load_rules()["applicant"]["employment_income_floors"]
    for emp_type, floor in floors.items():
        assert isinstance(floor, int) and floor > 0, (
            f"Income floor for {emp_type} must be a positive int, got {floor}"
        )


# ---------------------------------------------------------------------------
# _load_rules() — credit_score section
# ---------------------------------------------------------------------------

def test_credit_score_auto_reject_below_is_500():
    assert _load_rules()["credit_score"]["auto_reject_below"] == 500


def test_credit_score_mandatory_review_below_is_600():
    assert _load_rules()["credit_score"]["mandatory_review_below"] == 600


def test_credit_score_excellent_band_min_is_750():
    assert _load_rules()["credit_score"]["bands"]["excellent"]["min"] == 750


def test_credit_score_poor_band_max_is_below_auto_reject():
    rules = _load_rules()
    poor_max = rules["credit_score"]["bands"]["poor"]["max"]
    auto_reject = rules["credit_score"]["auto_reject_below"]
    assert poor_max >= auto_reject, (
        f"Poor band max ({poor_max}) should cover the auto-reject threshold ({auto_reject})"
    )


def test_credit_score_bands_are_contiguous():
    bands = _load_rules()["credit_score"]["bands"]
    ordered = sorted(bands.values(), key=lambda b: b["min"])
    for i in range(len(ordered) - 1):
        lower_max = ordered[i]["max"]
        upper_min = ordered[i + 1]["min"]
        assert upper_min == lower_max + 1, (
            f"Gap between bands: max={lower_max}, next min={upper_min}"
        )


# ---------------------------------------------------------------------------
# _load_rules() — income section
# ---------------------------------------------------------------------------

def test_income_min_annual_income_is_positive():
    income = _load_rules()["income"]
    assert income["min_annual_income"] > 0


def test_income_min_income_multiplier_is_integer():
    multiplier = _load_rules()["income"]["min_income_multiplier"]
    assert isinstance(multiplier, int) and multiplier >= 1


# ---------------------------------------------------------------------------
# _load_rules() — debt_to_income section
# ---------------------------------------------------------------------------

def test_dti_auto_reject_above_is_0_60():
    assert _load_rules()["debt_to_income"]["auto_reject_above"] == pytest.approx(0.60)


def test_dti_low_risk_max_is_0_30():
    assert _load_rules()["debt_to_income"]["low_risk"]["max"] == pytest.approx(0.30)


def test_dti_bands_are_ordered_low_medium_high():
    dti = _load_rules()["debt_to_income"]
    assert dti["low_risk"]["max"] < dti["medium_risk"]["max"] < dti["high_risk"]["max"]


# ---------------------------------------------------------------------------
# _load_rules() — risk_score section
# ---------------------------------------------------------------------------

def test_risk_score_weights_sum_to_one():
    weights = _load_rules()["risk_score"]["weights"]
    total = sum(weights.values())
    assert total == pytest.approx(1.0), f"Weights sum to {total}, expected 1.0"


def test_risk_score_weights_are_positive():
    for name, w in _load_rules()["risk_score"]["weights"].items():
        assert w > 0, f"Weight for {name} must be positive"


def test_risk_score_approved_below_less_than_review_required():
    rs = _load_rules()["risk_score"]
    assert rs["approved_below"] < rs["review_required_below"]


def test_risk_score_review_required_equals_rejected_above():
    rs = _load_rules()["risk_score"]
    assert rs["review_required_below"] == rs["rejected_above"]


def test_risk_score_min_max_range():
    rs = _load_rules()["risk_score"]
    assert rs["min_score"] == 0
    assert rs["max_score"] == 100


# ---------------------------------------------------------------------------
# _load_rules() — loan section
# ---------------------------------------------------------------------------

def test_loan_section_present():
    assert "loan" in _load_rules()


def test_loan_min_amount_less_than_max_amount():
    loan = _load_rules()["loan"]
    assert loan["min_amount"] < loan["max_amount"]


def test_loan_min_tenure_less_than_max_tenure():
    loan = _load_rules()["loan"]
    assert loan["min_tenure"] < loan["max_tenure"]


def test_loan_high_value_threshold_between_min_and_max():
    loan = _load_rules()["loan"]
    assert loan["min_amount"] < loan["high_value_threshold"] < loan["max_amount"]


# ---------------------------------------------------------------------------
# _load_rules() — compliance section
# ---------------------------------------------------------------------------

def test_compliance_case_id_prefix_is_CASE():
    assert _load_rules()["compliance"]["case_id_prefix"] == "CASE"


def test_compliance_retention_years_is_positive():
    assert _load_rules()["compliance"]["retention_years"] > 0


# ---------------------------------------------------------------------------
# _load_loan_rules() — basic contract
# ---------------------------------------------------------------------------

def test_loan_rules_yaml_loads_without_error():
    loan_rules = _load_loan_rules()
    assert isinstance(loan_rules, dict)
    assert len(loan_rules) > 0


def test_loan_rules_has_required_top_level_keys():
    loan_rules = _load_loan_rules()
    for key in ["employment", "credit", "dti", "risk_score", "loan", "agents"]:
        assert key in loan_rules, f"Missing top-level key in loan_rules: {key}"


def test_loan_rules_agents_has_max_response_tokens():
    agents = _load_loan_rules()["agents"]
    assert "max_response_tokens" in agents


def test_loan_rules_agents_max_tokens_covers_all_five_agents():
    tokens = _load_loan_rules()["agents"]["max_response_tokens"]
    for agent in ("applicant_profile", "financial_risk", "policy_knowledge",
                  "loan_decision", "compliance"):
        assert agent in tokens, f"Missing max_response_tokens entry for agent: {agent}"


def test_loan_rules_agents_temperature_covers_all_five_agents():
    temps = _load_loan_rules()["agents"]["temperature"]
    for agent in ("applicant_profile", "financial_risk", "policy_knowledge",
                  "loan_decision", "compliance"):
        assert agent in temps, f"Missing temperature entry for agent: {agent}"


def test_loan_rules_agents_temperature_values_in_range():
    for agent, temp in _load_loan_rules()["agents"]["temperature"].items():
        assert 0.0 <= temp <= 1.0, f"Temperature for {agent} ({temp}) out of [0, 1]"


def test_loan_rules_rag_top_k_chunks_is_positive_int():
    top_k = _load_loan_rules()["agents"]["rag"]["top_k_chunks"]
    assert isinstance(top_k, int) and top_k > 0


# ---------------------------------------------------------------------------
# get_settings() — defaults and convenience properties
# ---------------------------------------------------------------------------

def test_settings_aws_region_default_is_us_east_1():
    assert get_settings().aws_region == "us-east-1"


def test_settings_api_port_default_is_8000():
    assert get_settings().api_port == 8000


def test_settings_mcp_port_default_is_8080():
    assert get_settings().mcp_port == 8080


def test_settings_chroma_collection_name_is_non_empty():
    assert get_settings().chroma_collection_name != ""


def test_settings_dti_auto_reject_threshold_matches_rules():
    settings = get_settings()
    expected = settings.rules["debt_to_income"]["auto_reject_above"]
    assert settings.dti_auto_reject_threshold == pytest.approx(expected)


def test_settings_credit_score_auto_reject_threshold_is_500():
    assert get_settings().credit_score_auto_reject_threshold == 500


def test_settings_risk_score_thresholds_has_required_keys():
    thresholds = get_settings().risk_score_thresholds
    for key in ("approved_below", "review_required_below", "rejected_above"):
        assert key in thresholds, f"risk_score_thresholds missing key: {key}"


def test_settings_rag_top_k_is_positive_int():
    top_k = get_settings().rag_top_k
    assert isinstance(top_k, int) and top_k > 0


def test_settings_rules_populated_from_yaml():
    settings = get_settings()
    assert isinstance(settings.rules, dict) and len(settings.rules) > 0


def test_settings_loan_rules_populated_from_yaml():
    settings = get_settings()
    assert isinstance(settings.loan_rules, dict) and len(settings.loan_rules) > 0
