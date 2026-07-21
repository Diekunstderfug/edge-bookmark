# HIS/EMR Source Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate HIS structured facts from EMR document narrative facts so diagnosis display and QC reference data use HIS as the first reference while EMR remains document evidence.

**Architecture:** HIS structured data is the canonical source for diagnosis display, patient/visit facts, operations, and orders. EMR documents remain a separate narrative evidence layer; EMR-extracted diagnosis text must never overwrite the top-level `diagnosis`. The record payload keeps compatibility through top-level `diagnosis`, but in HIS mode that field is always derived from HIS `findDiagLs`.

**Tech Stack:** FastAPI, Pydantic, pytest, existing `HISRecordSource`, `DeciHISNormalizer`, and QC agent retrieval stack.

---

## File Structure

- Modify: `backend_py/clients/vendors/dcyy/normalizer.py`
  - Owns HIS/EMR source separation for normalized HIS records.
  - Builds HIS-only `diagnosis`, `diagnosis_source`, `his_structured`, and `emr_documents`.
- Modify: `backend_py/models.py`
  - Adds optional compatibility fields to `UnifiedMedicalRecord` for source-separated payloads.
- Modify: `backend_py/clients/vendors/dcyy/record_source.py`
  - Keeps list/detail semantics aligned with HIS-first diagnosis display and visit-summary separation.
- Modify: `backend_py/api/record_routes.py`
  - Ensures REST detail and diagnosis endpoints expose the intended source-separated contract.
- Modify: `backend_py/qc_agents/retrieval/his_structured_backend.py`
  - Feeds QC evidence with both HIS structured facts and EMR document mentions as distinct source layers.
- Modify: `backend_py/qc_agents/retrieval/evidence_builder.py`
  - Adds explicit source metadata and source-specific purpose labels.
- Modify: `docs/HIS_INTERFACE.md`, `docs/ARCHITECTURE.md`
  - Documents HIS as first reference and EMR as narrative evidence.
- Test: `tests/test_clients/test_deci_his_normalizer.py`
- Test: `tests/test_api/test_his_routes.py`
- Test: `tests/test_api/test_api_routes.py`
- Test: `tests/test_qc_agents/test_his_structured_backend.py`
- Test: `tests/test_qc_agents/test_evidence_builder.py`
- Test: `tests/test_qc_agents/test_evidence_builder_extended.py`

---

## Task 1: Normalize HIS and EMR Into Separate Layers

**Files:**
- Modify: `backend_py/clients/vendors/dcyy/normalizer.py`
- Modify: `backend_py/models.py`
- Test: `tests/test_clients/test_deci_his_normalizer.py`

- [ ] **Step 1: Add failing tests for HIS-only top-level diagnosis**

Add tests proving EMR document diagnosis does not override HIS structured diagnosis:

```python
def test_normalize_diagnosis_prefers_his_over_html(normalizer):
    result = normalizer.normalize(
        **_base_inputs(
            patient_info=_patient_info(patient_name="张三"),
            diagnoses=[
                _diagnosis(diag_name="HIS结构化肺炎", is_main_diagnosis=True),
                _diagnosis(diag_name="HIS结构化高血压", is_main_diagnosis=False),
            ],
            html_structured={"diagnosis": "文书诊断肺癌"},
        )
    )

    record = _as_record(result)
    assert record.diagnosis == "HIS结构化肺炎；HIS结构化高血压"
    assert record.diagnosis_source == "his_structured"
    assert record.his_structured["diagnosis_display"] == record.diagnosis
    assert record.emr_documents["extracted_fields"]["diagnosis_mentions"][0]["text"] == "文书诊断肺癌"
```

Add tests proving no HIS diagnosis means no top-level diagnosis:

```python
def test_normalize_html_diagnosis_does_not_create_top_level_diagnosis(normalizer):
    result = normalizer.normalize(
        **_base_inputs(
            patient_info=_patient_info(),
            diagnoses=[],
            html_structured={"diagnosis": "文书诊断肺癌"},
        )
    )

    record = _as_record(result)
    assert record.diagnosis is None
    assert record.diagnosis_source is None
    assert record.emr_documents["extracted_fields"]["diagnosis_mentions"][0]["text"] == "文书诊断肺癌"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_clients/test_deci_his_normalizer.py -q
```

Expected: new tests fail because `diagnosis` currently prefers `html_structured["diagnosis"]` and `UnifiedMedicalRecord` lacks declared source fields.

- [ ] **Step 3: Add source-separated fields to `UnifiedMedicalRecord`**

Add optional fields to `OptionalMedicalRecordFields`:

```python
diagnosis_source: str | None = None
his_structured: dict[str, Any] | None = None
emr_documents: dict[str, Any] | None = None
```

- [ ] **Step 4: Change `DeciHISNormalizer.normalize()` output**

Make the returned mapping include:

```python
diagnosis_display = self._normalize_diagnosis(diagnoses=diagnoses)

return {
    ...
    "diagnosis": diagnosis_display,
    "diagnosis_source": "his_structured" if diagnosis_display else None,
    "documents": documents,
    "patient_info": patient_info or None,
    "diagnoses": diagnoses,
    "operations": operations,
    "orders": orders,
    "his_structured": {
        "patient": patient_info or {},
        "visit": {
            "visit_id": record_id,
            "department": _first_non_none(
                _string_or_none(patient_info.get("dept_name")),
                _string_or_none(patient_info.get("dept_code")),
            ),
            "admission_date": _format_yyyymmdd(patient_info.get("time_admission")),
            "discharge_date": _format_yyyymmdd(patient_info.get("time_discharged")),
        },
        "diagnoses": diagnoses,
        "diagnosis_display": diagnosis_display,
        "operations": operations,
        "orders": orders,
    },
    "emr_documents": {
        "documents": documents,
        "extracted_fields": self._build_emr_extracted_fields(html_structured),
    },
}
```

- [ ] **Step 5: Replace diagnosis helper**

Change `_normalize_diagnosis()` to accept only HIS diagnoses:

```python
def _normalize_diagnosis(
    self,
    *,
    diagnoses: list[dict[str, object]],
) -> str | None:
    diagnosis_items: list[tuple[int, str]] = []
    for index, diagnosis in enumerate(diagnoses):
        name = _string_or_none(diagnosis.get("diag_name"))
        if name is None:
            continue
        priority = 0 if diagnosis.get("is_main_diagnosis") is True else 1
        diagnosis_items.append((priority * 100000 + index, name))

    if not diagnosis_items:
        return None

    diagnosis_items.sort(key=lambda item: item[0])
    return "；".join(name for _, name in diagnosis_items)
```

Add a helper for EMR extracted fields:

```python
def _build_emr_extracted_fields(
    self,
    html_structured: dict[str, str],
) -> dict[str, object]:
    extracted: dict[str, object] = {}
    diagnosis_text = _string_or_none(html_structured.get("diagnosis"))
    extracted["diagnosis_mentions"] = (
        [{"text": diagnosis_text, "source_layer": "emr_document"}]
        if diagnosis_text
        else []
    )
    for field in (
        "chief_complaint",
        "present_illness",
        "past_history",
        "personal_history",
        "family_history",
        "physical_exam",
        "auxiliary_exam",
        "treatment_plan",
        "department",
        "admission_date",
        "discharge_date",
    ):
        value = _string_or_none(html_structured.get(field))
        if value is not None:
            extracted[field] = [{"text": value, "source_layer": "emr_document"}]
    return extracted
```

- [ ] **Step 6: Run normalizer tests**

Run:

```bash
.venv/bin/pytest tests/test_clients/test_deci_his_normalizer.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 7: Commit Task 1**

Commit message:

```text
区分HIS诊断事实和EMR文书诊断来源

Constraint: 顶层 diagnosis 在 HIS 模式下只能来自 HIS 结构化诊断
Confidence: medium
Scope-risk: moderate
Directive: 不要再让 EMR 文书抽取诊断覆盖系统诊断展示字段
Tested: .venv/bin/pytest tests/test_clients/test_deci_his_normalizer.py -q
```

---

## Task 2: Align REST Record and List Semantics

**Files:**
- Modify: `backend_py/clients/vendors/dcyy/record_source.py`
- Modify: `backend_py/api/record_routes.py`
- Test: `tests/test_api/test_his_routes.py`
- Test: `tests/test_api/test_api_routes.py`

- [ ] **Step 1: Add failing API/list tests**

Add a HIS detail test where EMR diagnosis and HIS diagnosis differ. Assert:

```python
assert data["diagnosis"] == "HIS结构化肺炎"
assert data["diagnosis_source"] == "his_structured"
assert data["his_structured"]["diagnosis_display"] == "HIS结构化肺炎"
assert data["emr_documents"]["extracted_fields"]["diagnosis_mentions"][0]["text"] == "文书诊断肺癌"
```

Add a list response test asserting `admDiags` is not treated as final diagnosis:

```python
record = response.json()["records"][0]
assert record.get("diagnosis") in (None, "")
assert record["his_visit_summary"]["admission_diagnosis_summary"] == "入院摘要诊断"
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_api/test_his_routes.py tests/test_api/test_api_routes.py -q
```

Expected: new assertions fail until response shaping is updated.

- [ ] **Step 3: Separate HIS visit summary in list records**

In `HISRecordSource.fetch_records()`, change each list item so `adm_diags` is exposed as summary metadata:

```python
{
    "id": v.visit_id,
    "visit_id": v.visit_id,
    "patient_id": v.patient_id,
    "patient_name": v.patient_name,
    "department": v.dept_name or department,
    "department_code": v.dept_code,
    "admission_date": v.time_admission,
    "diagnosis": None,
    "diagnosis_source": "his_structured",
    "chief_complaint": v.complained_as,
    "visit_status": v.visit_status,
    "case_no": v.case_no,
    "bed_no": v.bed_no,
    "clinician_name": v.clinician_name,
    "his_visit_summary": {
        "admission_diagnosis_summary": v.adm_diags,
        "chief_complaint_summary": v.complained_as,
    },
}
```

Do not call `findDiagLs` per row in list mode; list mode remains lightweight.

- [ ] **Step 4: Preserve structured diagnosis endpoint**

Keep `/records/{visit_id}/diagnoses` behavior unchanged except for existing frontend aliases. Do not fold EMR document diagnosis into this endpoint.

- [ ] **Step 5: Run API tests**

Run:

```bash
.venv/bin/pytest tests/test_api/test_his_routes.py tests/test_api/test_api_routes.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit Task 2**

Commit message:

```text
让HIS列表和详情接口显式区分诊断来源

Constraint: 列表接口不能把 admDiags 当作完整结构化诊断
Confidence: medium
Scope-risk: moderate
Directive: /records/{visit_id}/diagnoses 才是 HIS 结构化诊断权威端点
Tested: .venv/bin/pytest tests/test_api/test_his_routes.py tests/test_api/test_api_routes.py -q
```

---

## Task 3: Split QC Evidence Into HIS and EMR Source Layers

**Files:**
- Modify: `backend_py/qc_agents/retrieval/his_structured_backend.py`
- Modify: `backend_py/qc_agents/retrieval/evidence_builder.py`
- Test: `tests/test_qc_agents/test_his_structured_backend.py`
- Test: `tests/test_qc_agents/test_evidence_builder.py`
- Test: `tests/test_qc_agents/test_evidence_builder_extended.py`

- [ ] **Step 1: Add failing evidence tests**

Update fake datasource records to include both:

```python
"diagnoses": [
    {
        "diag_name": "HIS结构化浸润性癌",
        "diag_type_name": "病理诊断",
        "time_diagnosed": "2026-01-20",
        "is_main_diagnosis": True,
    }
],
"emr_documents": {
    "extracted_fields": {
        "diagnosis_mentions": [
            {"text": "文书出院诊断：原位癌", "source_layer": "emr_document"}
        ]
    }
}
```

Assert HIS chunks have:

```python
assert chunk.provenance.doc_type == "his_diagnosis"
assert chunk.metadata["source_layer"] == "his_structured"
```

Assert EMR chunks have:

```python
assert chunk.provenance.doc_type == "emr_document"
assert chunk.metadata["source_layer"] == "emr_document"
assert chunk.text == "文书出院诊断：原位癌"
```

- [ ] **Step 2: Run QC evidence tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_qc_agents/test_his_structured_backend.py tests/test_qc_agents/test_evidence_builder.py tests/test_qc_agents/test_evidence_builder_extended.py -q
```

Expected: source-layer assertions fail before implementation.

- [ ] **Step 3: Pass EMR mentions into evidence builder**

In `HIStructuredRetrievalBackend.run_recipe()`, extract:

```python
emr_diagnosis_mentions = []
emr_documents = record.get("emr_documents") if isinstance(record, dict) else None
if isinstance(emr_documents, dict):
    extracted_fields = emr_documents.get("extracted_fields")
    if isinstance(extracted_fields, dict):
        raw_mentions = extracted_fields.get("diagnosis_mentions")
        if isinstance(raw_mentions, list):
            emr_diagnosis_mentions = [
                item for item in raw_mentions if isinstance(item, dict)
            ]
```

Pass `emr_diagnosis_mentions=emr_diagnosis_mentions` into `build_from_his_structured()`.

- [ ] **Step 4: Extend `StructuredEvidenceBuilder`**

Add an optional parameter:

```python
emr_diagnosis_mentions: list[dict] | None = None
```

Add HIS metadata to diagnosis chunks:

```python
metadata={
    "source_layer": "his_structured",
    "is_main_diagnosis": is_main_diagnosis,
    "diag_code": diag_code,
}
```

Add EMR diagnosis mention chunks under a separate group:

```python
EvidenceGroup(
    sub_intent="extract.emr_document_diagnosis",
    purpose="EMR文书诊断描述",
    required=False,
    status="found" if chunks else "missing",
    chunks=chunks,
)
```

Each EMR chunk uses:

```python
EvidenceChunk(
    evidence_id=f"emr_diag_{uuid.uuid4().hex[:8]}",
    doc_id="emr_document_diagnosis",
    chunk_id=f"emr_diag_{uuid.uuid4().hex[:8]}",
    patient_internal_id="",
    encounter_id="",
    text=text,
    evidence_tier=qc_constants.EVIDENCE_TIER_CLINICAL_NARRATIVE,
    objectivity="clinical_assessment",
    provenance=EvidenceProvenance(
        doc_type="emr_document",
        section="文书诊断描述",
    ),
    metadata={"source_layer": "emr_document"},
)
```

- [ ] **Step 5: Run QC evidence tests**

Run:

```bash
.venv/bin/pytest tests/test_qc_agents/test_his_structured_backend.py tests/test_qc_agents/test_evidence_builder.py tests/test_qc_agents/test_evidence_builder_extended.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit Task 3**

Commit message:

```text
将质控证据拆成HIS结构化和EMR文书来源

Constraint: 诊断一致性质控必须能区分系统诊断和文书描述
Confidence: medium
Scope-risk: moderate
Directive: 新证据类型必须带 source_layer，避免模型混用来源
Tested: .venv/bin/pytest tests/test_qc_agents/test_his_structured_backend.py tests/test_qc_agents/test_evidence_builder.py tests/test_qc_agents/test_evidence_builder_extended.py -q
```

---

## Task 4: Document the Source Policy

**Files:**
- Modify: `docs/HIS_INTERFACE.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update HIS interface documentation**

Add a section stating:

```markdown
### HIS/EMR 来源边界

- `findDiagLs` 是 HIS 结构化诊断权威来源。
- HIS 模式下顶层 `diagnosis` 只能由 `findDiagLs` 派生。
- `GetBLWJ` 文书内容中抽取到的诊断只进入 `emr_documents.extracted_fields.diagnosis_mentions`。
- `findVisitRecordsByOrgAndDept.admDiags` 是列表摘要字段，只可展示为 `his_visit_summary.admission_diagnosis_summary`，不能替代 `findDiagLs`。
```

- [ ] **Step 2: Update architecture documentation**

Add the policy:

```markdown
HIS structured layer is the first reference for patient/visit facts, diagnosis, operations, and orders. EMR document layer stores narrative text and extracted mentions for evidence comparison only. In HIS mode, top-level `diagnosis` is HIS-only.
```

- [ ] **Step 3: Run documentation hygiene**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Commit Task 4**

Commit message:

```text
记录HIS与EMR诊断来源边界

Constraint: 后续实现必须保持 HIS 为诊断展示和质控第一参照物
Confidence: high
Scope-risk: narrow
Directive: 文书诊断只能作为 EMR 证据层，不能覆盖系统诊断字段
Tested: git diff --check
```

---

## Task 5: Unified Verification and Final Review

**Files:**
- No new feature files.
- Verify all modified files from Tasks 1-4.

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
.venv/bin/pytest tests/test_clients/test_deci_his_normalizer.py -q
.venv/bin/pytest tests/test_api/test_his_routes.py tests/test_api/test_api_routes.py -q
.venv/bin/pytest tests/test_qc_agents/test_his_structured_backend.py tests/test_qc_agents/test_evidence_builder.py tests/test_qc_agents/test_evidence_builder_extended.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run broad backend regression**

Run:

```bash
.venv/bin/pytest tests/ -q
```

Expected: all tests pass or only pre-existing unrelated failures are documented with exact test names.

- [ ] **Step 3: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Inspect final payload contract**

Review the final diff and confirm:

```text
top-level diagnosis = HIS findDiagLs derived display
diagnosis_source = his_structured when diagnosis exists
emr_documents.extracted_fields.diagnosis_mentions contains document diagnosis text
/records/{visit_id}/diagnoses returns only HIS structured diagnoses
QC evidence has source_layer his_structured or emr_document
```

- [ ] **Step 5: Final commit if needed**

If previous tasks were not committed separately, make one Chinese Lore-style commit:

```text
按来源拆分HIS诊断和EMR文书证据

Constraint: HIS 结构化诊断是展示和质控第一参照物
Rejected: 继续复用顶层 diagnosis 混放文书抽取结果 | 会让模型和前端无法区分系统事实与文书描述
Confidence: medium
Scope-risk: moderate
Directive: 不要让 EMR 文书诊断覆盖 HIS 结构化诊断
Tested: .venv/bin/pytest tests/test_clients/test_deci_his_normalizer.py -q; .venv/bin/pytest tests/test_api/test_his_routes.py tests/test_api/test_api_routes.py -q; .venv/bin/pytest tests/test_qc_agents/test_his_structured_backend.py tests/test_qc_agents/test_evidence_builder.py tests/test_qc_agents/test_evidence_builder_extended.py -q; git diff --check
Not-tested: full tests/ only if runtime exceeds available CI window or reveals unrelated pre-existing failures
```

---

## Parallel Execution Notes

- Task 1 and Task 3 can run in parallel after agreeing on field names: `his_structured`, `emr_documents`, and `diagnosis_source`.
- Task 2 depends on Task 1 because REST detail shape comes from the normalizer.
- Task 4 can run in parallel with Tasks 1-3.
- Task 5 must run after all patches are merged.

## Acceptance Criteria

- HIS mode top-level `diagnosis` never uses EMR document extraction.
- EMR document diagnosis is still preserved and traceable for model comparison.
- Diagnosis display endpoints use HIS structured data as first reference.
- QC evidence explicitly separates `his_structured` and `emr_document`.
- Targeted regression tests and `git diff --check` pass.
