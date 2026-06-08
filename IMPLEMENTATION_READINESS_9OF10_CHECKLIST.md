# Implementation Readiness 9/10 Checklist

## Objective
Raise Code / Implementation Readiness from 7/10 to 9/10 by proving executable, test-backed, end-to-end behavior for APPROVED, REJECTED, and REVIEW_REQUIRED scenarios.

## Success Definition
All checklist sections below are completed, evidence artifacts are generated, and no critical test path is skipped.

---

## 1. Test Activation (No Critical Skips)

### Actions
- Remove `@pytest.mark.skip` from core unit and integration suites:
  - `tests/unit/test_applicant_profile_agent.py`
  - `tests/unit/test_financial_risk_agent.py`
  - `tests/unit/test_policy_knowledge_agent.py`
  - `tests/unit/test_loan_decision_agent.py`
  - `tests/unit/test_compliance_agent.py`
  - `tests/integration/test_api_endpoints.py`
  - `tests/integration/test_full_pipeline.py`

### Acceptance Criteria
- No skip markers remain in the above files for core scenario tests.
- Each test has concrete assertions (not placeholders).

### Verification Command
```powershell
python -m pytest -q tests/unit tests/integration
```

---

## 2. End-to-End Verdict Coverage

### Actions
- Add/complete integration tests that verify full workflow outputs for:
  - APPROVED
  - REJECTED
  - REVIEW_REQUIRED
- Use `tests/fixtures/sample_applications.json` as canonical inputs.

### Mandatory Assertions
- `verdict`, `confidence_score`, `explanation`, `case_id` always present.
- For REVIEW_REQUIRED, assert all manual-review action fields are present:
  - `action_taken`
  - `notification_status`
  - `review_queue`
  - `manual_review_owner`
  - `reviewer_role`
  - `review_due_timestamp`
  - `review_status`
  - `status_transition`
  - `transition_history`

### Verification Command
```powershell
python -m pytest -q tests/integration/test_full_pipeline.py
```

---

## 3. API Contract Validation

### Actions
- Ensure API tests validate response schema from `api/models/response.py`.
- Add negative-path tests for invalid payloads and upstream failures.

### Acceptance Criteria
- `POST /api/v1/analyze` contract tests pass for all verdicts.
- Validation and error-path tests pass with expected status codes.

### Verification Command
```powershell
python -m pytest -q tests/integration/test_api_endpoints.py
```

---

## 4. Manual Review Lifecycle Maturity

### Actions
- Extend review lifecycle beyond initial queueing in `mcp/tools/review_action_tools.py` and orchestration flow:
  - Assignment transition
  - In-review transition
  - Escalation transition (SLA breach)
  - Closure transition (approved_final/rejected_final)
- Persist each transition in audit logs via `agents/compliance_agent.py`.

### Acceptance Criteria
- Lifecycle transitions are deterministic and test-asserted.
- `transition_history` is append-only and time-ordered.

### Suggested Test Additions
- New test file: `tests/unit/test_review_action_tools.py`
- Transition tests for each lifecycle state edge.

---

## 5. Runtime Compliance Proof

### Actions
- Keep and run LLM runtime compliance checks.
- Capture command output as evaluator evidence.

### Verification Command
```powershell
python -m pytest -q tests/unit/test_llm_runtime_compliance.py
```

### Acceptance Criteria
- Passes with 3/3 checks:
  - Sonnet 4.6 target configured
  - Anthropic SDK path present
  - boto3 fallback path present

---

## 6. Reproducible Evidence Bundle

### Actions
- Produce one folder with all review artifacts:
  - test output logs
  - sample API responses (APPROVED/REJECTED/REVIEW_REQUIRED)
  - sample audit log entries
  - environment and command manifest

### Recommended Folder
- `evidence/readiness_9of10/`

### Required Files
- `evidence/readiness_9of10/commands_run.txt`
- `evidence/readiness_9of10/test_summary.txt`
- `evidence/readiness_9of10/api_samples.json`
- `evidence/readiness_9of10/audit_samples.jsonl`

### Acceptance Criteria
- An evaluator can reproduce outcomes by following `commands_run.txt` exactly.

---

## 7. CI Gate for Readiness

### Actions
- Add CI checks that fail on:
  - failing tests
  - critical skipped tests
  - contract regression in response model fields

### Acceptance Criteria
- Pull request cannot merge if readiness checks fail.

---

## 8. One-Command Evaluator Run

### Target
Provide a single command for evaluators.

### Example
```powershell
python -m pytest -q tests/unit/test_llm_runtime_compliance.py tests/unit tests/integration
```

### Acceptance Criteria
- Command exits 0.
- Generates enough logs to support evaluation.

---

## 9. Final Readiness Checklist (Go/No-Go)

Mark all before claiming 9/10:
- [ ] Core unit tests enabled and passing
- [ ] Integration tests enabled and passing
- [ ] All three verdict types verified end-to-end
- [ ] REVIEW_REQUIRED action lifecycle fields fully asserted
- [ ] Lifecycle transitions beyond queueing are implemented and tested
- [ ] LLM runtime compliance tests pass
- [ ] Evidence bundle generated and reproducible
- [ ] CI gates enforce readiness automatically

---

## Expected Outcome
If all items are completed and evidenced, Code / Implementation Readiness can be justified at 9/10 with strong reviewer confidence.