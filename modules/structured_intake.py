"""
modules/structured_intake.py

Structured data input adapter for ONTO.
Implements Stage 1 input adapter: JSON, CSV, database records.
(ROADMAP-001 — Stage 1 current sprint, structured data adapter)

Architecture
────────────
  Raw structured input (JSON string/dict | CSV string | list of dicts)
       ↓
  receive_json() / receive_csv() / receive_records()
       ↓  intake package (same contract as modules.intake.receive())
       ↓
  CONTEXTUALIZE → SURFACE → GOVERN → REMEMBER  (unchanged)

Adapter contract (per ROADMAP-001):
  1. Convert raw input to a classified intake package
  2. Set source_type correctly  →  "structured"
  3. Apply classification based on content, not format
  4. Preserve provenance — structured_type, field count, row count
  5. Never introduce synthetic data — every field traces to input
  6. Never bypass safety checks — safety runs on all text values

Field-level classification
──────────────────────────
Each distinct value in the structured input is classified individually.
The package classification is the maximum across all fields.
`field_classifications` maps dot-notation field paths to their level.

Example (JSON)::
  {"name": "Alice", "ssn": "123-45-6789"}
  → field_classifications: {"name": 2, "ssn": 3}
  → classification: 3

Nested JSON is flattened to dot-notation paths::
  {"address": {"city": "New York"}}
  → field_classifications: {"address.city": 0}

CSV rows are flattened as  row_N.field_name::
  header row + data row 0: {"row_0.name": 2, "row_0.ssn": 3}
  package classification: max across all rows

Plain English: This adapter lets ONTO understand structured data
the same way it understands sentences — everything classified,
everything safety-checked, every field traceable.
"""

import csv
import io
import json
from typing import Any, Dict, List, Optional, Tuple, Union

# Import classification and safety helpers from the text intake module.
# These are the same checks — field values receive identical treatment.
from modules.intake import (
    _assess_complexity,
    _check_safety,
    _classify,
    _sanitize,
)

# Maximum number of rows processed from CSV/records.
# Prevents runaway memory use on large imports.
MAX_ROWS: int = 1_000

# Maximum number of fields in a single JSON object (depth-first flattened).
MAX_FIELDS: int = 500


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────────────────────────


def receive_json(
    data: Union[str, Dict[str, Any]],
    *,
    source_hint: str = "",
) -> Dict[str, Any]:
    """
    Receives a JSON value (string or dict) and produces an intake package.

    Args:
        data:        A JSON string or a Python dict/list.
        source_hint: Optional provenance label ("database", "api_response", …).

    Returns:
        Intake package dict compatible with modules.intake.receive() output.

    On invalid JSON:
        Returns an error package with classification=0 and safety=None.
        The raw input is still recorded for audit purposes.
    """
    # 1. Parse to Python object
    raw_repr: str
    parsed: Any

    if isinstance(data, str):
        raw_repr = data
        try:
            parsed = json.loads(data)
        except (json.JSONDecodeError, ValueError) as exc:
            return _error_package(
                raw=data,
                reason=f"json_parse_error: {exc}",
                structured_type="json",
                source_hint=source_hint,
            )
    else:
        parsed = data
        try:
            raw_repr = json.dumps(data, default=str)
        except (TypeError, ValueError):
            raw_repr = str(data)

    # 2. Flatten to {path: value_string} pairs
    fields = _flatten(parsed)

    # 3. Build the package from flattened fields
    return _build_package(
        raw_repr=raw_repr,
        fields=fields,
        structured_type="json",
        source_hint=source_hint,
    )


def receive_csv(
    csv_text: str,
    *,
    has_header: bool = True,
    source_hint: str = "",
) -> Dict[str, Any]:
    """
    Receives a CSV string and produces an intake package.

    Each row is classified independently.  The package classification is the
    maximum across all rows.  `records` in the package contains the parsed
    rows as a list of dicts (with header names if available) or lists.

    Args:
        csv_text:   Raw CSV string (may contain newlines).
        has_header: If True, first row is treated as column headers.
        source_hint: Optional provenance label.

    Returns:
        Intake package dict.
    """
    if not isinstance(csv_text, str):
        return _error_package(
            raw=str(csv_text),
            reason="csv_type_error: input must be a string",
            structured_type="csv",
            source_hint=source_hint,
        )

    try:
        reader = csv.reader(io.StringIO(csv_text))
        all_rows = list(reader)
    except csv.Error as exc:
        return _error_package(
            raw=csv_text,
            reason=f"csv_parse_error: {exc}",
            structured_type="csv",
            source_hint=source_hint,
        )

    if not all_rows:
        return _build_package(
            raw_repr=csv_text,
            fields={},
            structured_type="csv",
            source_hint=source_hint,
            extra={"records": [], "row_count": 0},
        )

    # Determine column names
    if has_header and len(all_rows) > 0:
        headers = [str(h).strip() for h in all_rows[0]]
        data_rows = all_rows[1:]
    else:
        # Synthetic column names: col_0, col_1, …
        headers = [f"col_{i}" for i in range(len(all_rows[0]))]
        data_rows = all_rows

    # Cap row count
    data_rows = data_rows[:MAX_ROWS]

    # Build records list and flattened field map
    records: List[Dict[str, str]] = []
    all_fields: Dict[str, str] = {}

    for row_idx, row in enumerate(data_rows):
        record: Dict[str, str] = {}
        for col_idx, cell in enumerate(row):
            col_name = headers[col_idx] if col_idx < len(headers) else f"col_{col_idx}"
            field_path = f"row_{row_idx}.{col_name}"
            cell_str = str(cell)
            record[col_name] = cell_str
            all_fields[field_path] = cell_str
        records.append(record)

    return _build_package(
        raw_repr=csv_text,
        fields=all_fields,
        structured_type="csv",
        source_hint=source_hint,
        extra={
            "records": records,
            "row_count": len(records),
            "headers": headers,
        },
    )


def receive_records(
    records: List[Dict[str, Any]],
    *,
    source_hint: str = "",
) -> Dict[str, Any]:
    """
    Receives a list of dicts (e.g., database query results) and produces
    an intake package.

    Each record is flattened and classified independently.  The package
    classification is the maximum across all records.

    Args:
        records:     List of dicts.  Values may be any scalar or nested type.
        source_hint: Optional provenance label ("db_query", "api_results", …).

    Returns:
        Intake package dict.
    """
    if not isinstance(records, list):
        return _error_package(
            raw=str(records),
            reason="records_type_error: input must be a list",
            structured_type="records",
            source_hint=source_hint,
        )

    try:
        raw_repr = json.dumps(records, default=str)
    except (TypeError, ValueError):
        raw_repr = str(records)

    # Cap rows
    capped = records[:MAX_ROWS]

    all_fields: Dict[str, str] = {}
    for row_idx, record in enumerate(capped):
        if not isinstance(record, dict):
            # Non-dict row — treat as a single value
            all_fields[f"row_{row_idx}"] = str(record)
            continue
        sub_fields = _flatten(record)
        for path, val in sub_fields.items():
            all_fields[f"row_{row_idx}.{path}"] = val

    return _build_package(
        raw_repr=raw_repr,
        fields=all_fields,
        structured_type="records",
        source_hint=source_hint,
        extra={"row_count": len(capped)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def _flatten(
    obj: Any,
    *,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 10,
) -> Dict[str, str]:
    """
    Recursively flattens a nested dict/list to dot-notation field paths.

    Examples::
        {"a": {"b": 1}} → {"a.b": "1"}
        {"tags": [1, 2]} → {"tags.0": "1", "tags.1": "2"}
        "plain string"   → {"": "plain string"}

    Args:
        obj:       The value to flatten.
        prefix:    Accumulated dot-notation path.
        depth:     Current recursion depth.
        max_depth: Maximum recursion depth (prevents runaway on circular refs).

    Returns:
        Dict mapping dot-notation paths to string-coerced values.
    """
    result: Dict[str, str] = {}

    if depth > max_depth:
        result[prefix] = str(obj)
        return result

    if isinstance(obj, dict):
        for key, val in obj.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            sub = _flatten(val, prefix=new_prefix, depth=depth + 1, max_depth=max_depth)
            result.update(sub)
            if len(result) >= MAX_FIELDS:
                break
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            new_prefix = f"{prefix}.{idx}" if prefix else str(idx)
            sub = _flatten(val, prefix=new_prefix, depth=depth + 1, max_depth=max_depth)
            result.update(sub)
            if len(result) >= MAX_FIELDS:
                break
    elif obj is None:
        # Null field — explicit empty string; still recorded for audit
        result[prefix] = ""
    else:
        result[prefix] = str(obj)

    return result


def _classify_fields(
    fields: Dict[str, str],
) -> Tuple[int, Dict[str, int]]:
    """
    Classifies each field value individually.

    Returns:
        (max_classification, {field_path: classification_level})
    """
    field_classifications: Dict[str, int] = {}
    max_level = 0

    for path, value in fields.items():
        level = _classify(value)
        field_classifications[path] = level
        if level > max_level:
            max_level = level

    return max_level, field_classifications


def _safety_check_all(fields: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Runs safety check on all field values concatenated.

    A crisis or harm signal in ANY field triggers the safety response.
    The check is done on the concatenated text — same logic as text intake.
    Returns the first non-None safety result found, or None if all clear.
    """
    for value in fields.values():
        result = _check_safety(value)
        if result is not None:
            return result
    return None


def _build_package(
    *,
    raw_repr: str,
    fields: Dict[str, str],
    structured_type: str,
    source_hint: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Builds the standard intake package from flattened fields.

    The package is structurally compatible with modules.intake.receive().
    Extra adapter-specific keys are namespaced under "structured_*".
    """
    from modules import memory
    from core.config import config as _config

    # Classification: per-field then package-level max
    classification, field_classifications = _classify_fields(fields)

    # Safety: over all field values
    safety = _safety_check_all(fields)

    # Sanitize the canonical representation
    clean, was_sanitized, was_truncated = _sanitize(raw_repr)

    # Complexity and word count of the full serialised representation
    word_count = len(clean.split()) if clean else 0
    complexity = _assess_complexity(clean, word_count)

    # Legal basis (same as text intake)
    legal_basis = _config.COMPLIANCE_LEGAL_BASIS_DEFAULT

    # Audit record
    record_id = memory.record(
        event_type="INTAKE",
        input_data=clean[:500] if clean else None,
        context={
            "sanitized": was_sanitized,
            "truncated": was_truncated,
            "input_type": f"structured_{structured_type}",
            "complexity": complexity,
            "classification": classification,
            "word_count": word_count,
            "legal_basis": legal_basis,
            "field_count": len(fields),
            "structured_type": structured_type,
            "source_hint": source_hint,
        },
        notes=(
            f"source:structured | type:{structured_type} | "
            f"fields:{len(fields)} | complexity:{complexity} | "
            f"legal_basis:{legal_basis}"
        ),
        classification=classification,
    )

    package: Dict[str, Any] = {
        # ── Standard intake fields (same contract as modules.intake.receive) ──
        "raw": raw_repr,
        "clean": clean,
        "input_type": f"structured_{structured_type}",
        "source": "structured",
        "word_count": word_count,
        "complexity": complexity,
        "safety": safety,
        "sanitized": was_sanitized,
        "truncated": was_truncated,
        "record_id": record_id,
        "classification": classification,
        "classification_basis": "field-level-auto",
        "legal_basis": legal_basis,
        # ── Structured-specific fields ────────────────────────────────────────
        "structured_type": structured_type,
        "source_hint": source_hint,
        "field_count": len(fields),
        "field_classifications": field_classifications,
    }

    if extra:
        package.update(extra)

    return package


def _error_package(
    *,
    raw: str,
    reason: str,
    structured_type: str,
    source_hint: str,
) -> Dict[str, Any]:
    """
    Returns a minimal error package when input cannot be parsed.

    The raw input is preserved for audit; classification defaults to 0;
    safety is None (unparseable input cannot be safety-checked).
    `parse_error` key signals the adapter failure to the caller.
    """
    from modules import memory
    from core.config import config as _config

    legal_basis = _config.COMPLIANCE_LEGAL_BASIS_DEFAULT

    record_id = memory.record(
        event_type="INTAKE",
        input_data=raw[:500] if raw else None,
        context={
            "sanitized": False,
            "truncated": False,
            "input_type": f"structured_{structured_type}",
            "complexity": "empty",
            "classification": 0,
            "word_count": 0,
            "legal_basis": legal_basis,
            "parse_error": reason,
            "structured_type": structured_type,
            "source_hint": source_hint,
        },
        notes=f"source:structured | type:{structured_type} | error:{reason}",
        classification=0,
    )

    return {
        "raw": raw,
        "clean": "",
        "input_type": f"structured_{structured_type}",
        "source": "structured",
        "word_count": 0,
        "complexity": "empty",
        "safety": None,
        "sanitized": False,
        "truncated": False,
        "record_id": record_id,
        "classification": 0,
        "classification_basis": "field-level-auto",
        "legal_basis": legal_basis,
        "structured_type": structured_type,
        "source_hint": source_hint,
        "field_count": 0,
        "field_classifications": {},
        "parse_error": reason,
    }
