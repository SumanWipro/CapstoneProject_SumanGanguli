# Applicant Profile Agent Output Field Alignment - TO DO List

## Problem Summary
The Applicant Profile Agent currently outputs fields that don't match the case study requirements. The agent must output the exact field names specified in the case study for full compliance.

**Current Output Fields:**
- `valid` (boolean)
- `flags` (list)
- `employment_band` (string)
- `age_eligible` (boolean)
- `income_consistent` (boolean)

**Required Output Fields (Case Study):**
- `income_stability_score` (numeric, 0-100 or 0-1)
- `employment_risk` (categorical or numeric)
- `credit_history_summary` (string describing credit profile)
- `completeness_flags` (list of validation/data quality flags)

---

## TO DO Items

### Phase 1: Analysis & Design (Planning Only)

- [ ] **TODO 1.1**: Review agents/applicant_profile_agent.py and identify where output dict is constructed
  - Location: Return statement in ApplicantProfileAgent.execute() or run() method
  - Look for: Dictionary with keys: valid, flags, employment_band, age_eligible, income_consistent
  
- [ ] **TODO 1.2**: Map current fields to required fields
  - Document transformation needed:
    - `employment_band` (e.g., "stable", "moderate", "unstable") → `employment_risk` (quantify: low=0.2, moderate=0.5, high=0.8)
    - `income_consistent` (boolean) → Component of `income_stability_score` (0-100)
    - `age_eligible` (boolean) → Component of `completeness_flags`
    - `flags` (existing list) → `completeness_flags` (rename + enhance)
    - Missing: `credit_history_summary` (needs to be derived or added)

- [ ] **TODO 1.3**: Identify data sources for new fields
  - Where will `income_stability_score` be calculated? (income_consistent, income variance, employment type)
  - Where will `credit_history_summary` come from? (credit_score range, CIBIL interpretation)
  - What logic determines `employment_risk`? (employment_type, employment_band mapping)

- [ ] **TODO 1.4**: Review mcp/tools/profile_tools.py for corresponding MCP tool definitions
  - Check if MCP tool schema needs updating to match new field names
  - Verify tool documentation and examples align with new output contract

- [ ] **TODO 1.5**: Check prompts/applicant_profile.txt for expected output format
  - Verify prompt template includes directives for new field names
  - Ensure prompt instructs Claude to output: income_stability_score, employment_risk, credit_history_summary, completeness_flags

---

### Phase 2: Implementation Planning (Code Changes - NOT YET)

- [ ] **TODO 2.1**: Plan income_stability_score calculation logic
  - Input factors: income_consistent (T/F), employment_type, income amount
  - Output range: 0-100 or 0.0-1.0 (choose one)
  - Scoring algorithm: (e.g., if consistent + salaried → 85, if inconsistent + self_employed → 45)

- [ ] **TODO 2.2**: Plan employment_risk transformation logic
  - Input: employment_band (stable/moderate/unstable)
  - Output: employment_risk with numeric/categorical value
  - Mapping: stable → low risk (0.2), moderate → medium risk (0.5), unstable → high risk (0.8)

- [ ] **TODO 2.3**: Plan credit_history_summary generation logic
  - Input: credit_score (from applicant data)
  - Output: Human-readable summary (e.g., "Good credit history (720 CIBIL): meets lending standards")
  - Ranges: 300-549 (Poor), 550-649 (Fair), 650-749 (Good), 750-900 (Excellent)

- [ ] **TODO 2.4**: Plan completeness_flags structure
  - Current `flags` list format: List[str] or List[dict]?
  - New `completeness_flags` should include:
    - Age eligibility status
    - Income consistency status
    - Existing flags (renamed)
    - Any new validation flags
  - Format: Keep consistent with existing flag structure

- [ ] **TODO 2.5**: Design output contract (TypedDict or docstring)
  - Create clear interface for ApplicantProfileOutput
  - Define types: income_stability_score: float, employment_risk: str/float, etc.
  - Document valid ranges and enum values

---

### Phase 3: Validation & Testing Planning (Verification - NOT YET)

- [ ] **TODO 3.1**: Plan unit test for income_stability_score calculation
  - Test case 1: Consistent salaried income → expect high score (80+)
  - Test case 2: Inconsistent self_employed income → expect medium score (40-60)
  - Test case 3: Inconsistent contract income → expect low score (<40)

- [ ] **TODO 3.2**: Plan unit test for employment_risk mapping
  - Test case 1: employment_band="stable" → employment_risk=0.2 (or "low")
  - Test case 2: employment_band="moderate" → employment_risk=0.5 (or "medium")
  - Test case 3: employment_band="unstable" → employment_risk=0.8 (or "high")

- [ ] **TODO 3.3**: Plan unit test for credit_history_summary
  - Test case 1: credit_score=720 → summary contains "Good"
  - Test case 2: credit_score=450 → summary contains "Poor"
  - Test case 3: credit_score=800 → summary contains "Excellent"

- [ ] **TODO 3.4**: Plan integration test for full output contract
  - Input: Sample applicant profile data
  - Verify output dict has all 4 required keys (no more, no less)
  - Verify no legacy keys (employment_band, age_eligible, income_consistent) remain
  - Verify all values pass type checks

- [ ] **TODO 3.5**: Plan backward compatibility audit
  - Search for code that depends on old field names (employment_band, flags, valid, etc.)
  - List files/functions that will need updates:
    - orchestrator/nodes.py (if it accesses agent output fields)
    - api/models/agents.py (if output schema is defined there)
    - tests/unit/test_applicant_profile_agent.py (if it checks old fields)
    - Any other nodes that consume ApplicantProfileAgent output

---

### Phase 4: Documentation Planning (NOT YET)

- [ ] **TODO 4.1**: Update CLAUDE.md with new Applicant Profile Agent output schema
  - Add new section: "Applicant Profile Agent Output Contract"
  - Document: income_stability_score, employment_risk, credit_history_summary, completeness_flags
  - Include: Field definitions, types, valid ranges, examples

- [ ] **TODO 4.2**: Update agent docstring in agents/applicant_profile_agent.py
  - Update class docstring with new output field descriptions
  - Update execute() method docstring with return type and field definitions

- [ ] **TODO 4.3**: Update MCP tool documentation in mcp/tools/profile_tools.py
  - Update tool description to match new output fields
  - Update example output to show new schema

- [ ] **TODO 4.4**: Update prompt template prompts/applicant_profile.txt
  - Add explicit instruction: "Output must include fields: income_stability_score, employment_risk, credit_history_summary, completeness_flags"
  - Provide examples for each field
  - Remove references to old field names

- [ ] **TODO 4.5**: Update README.md case study compliance section
  - Mark "Applicant Profile Agent output" as "Fully Met"
  - Document exact field names and calculations

---

## Summary of Changes Required

**Files to Modify:**
1. `agents/applicant_profile_agent.py` - Output dict construction
2. `mcp/tools/profile_tools.py` - MCP tool schema
3. `prompts/applicant_profile.txt` - Agent prompt template
4. `api/models/agents.py` - Output model (if exists)
5. `tests/unit/test_applicant_profile_agent.py` - Test assertions
6. `orchestrator/nodes.py` - Field access (if needed)
7. `CLAUDE.md` - Documentation
8. `README.md` - Compliance matrix

**New/Modified Fields:**
- ADD: `income_stability_score` (float, 0-100 or 0.0-1.0)
- ADD: `employment_risk` (float 0-1 or string: low/medium/high)
- ADD: `credit_history_summary` (string, human-readable)
- RENAME: `flags` → `completeness_flags`
- REMOVE: `employment_band`, `age_eligible`, `income_consistent` (or move to completeness_flags)
- REMOVE: `valid` (or consolidate into completeness_flags)

**Calculation Logic to Define:**
1. income_stability_score = f(income_consistent, employment_type, income_amount)
2. employment_risk = map(employment_band) → numeric value
3. credit_history_summary = f(credit_score) → readable text
4. completeness_flags = enhance(flags) → include all validation status info

---

## Priority

**High Priority**: 
- TODO 1.1 - 1.5 (Identify current implementation)
- TODO 2.1 - 2.5 (Plan implementation approach)
- TODO 4.1 (Update case study compliance reference)

**Medium Priority**:
- TODO 3.1 - 3.5 (Plan validation)
- TODO 4.2 - 4.5 (Update documentation)

---

## Exit Criteria

When all TO DOs are addressed:
- ✅ Applicant Profile Agent outputs exactly 4 fields with case study names
- ✅ No legacy field names in output
- ✅ All output fields properly calculated/transformed from internal data
- ✅ Credit history summary added (was missing)
- ✅ Case study requirement marked "Fully Met"
- ✅ Unit tests validate new output contract
- ✅ No breaking changes to downstream consumers (or all updated)
- ✅ Documentation updated with new schema

