#!/usr/bin/env python3
"""
Validate Royalty Allocation Ledger Agent examples.

Validation layers:
1. JSON Schema validation
2. Record-specific semantic validation
3. Approval and safety-boundary validation
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationTarget:
    """Schema and example pair to validate."""

    name: str
    schema_path: Path
    example_path: Path
    semantic_validator: Callable[[dict[str, Any]], list[str]]


def load_document(path: Path) -> Any:
    """Load a JSON or YAML document."""

    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() == ".json":
            return json.load(file)

        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(file)

    raise ValueError(f"Unsupported file type: {path}")


def decimal_value(value: Any, field_name: str) -> Decimal:
    """Convert a value to Decimal."""

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be a valid numeric value: {value!r}"
        ) from error


def approximately_equal(
    left: Decimal,
    right: Decimal,
    tolerance: Decimal,
) -> bool:
    """Return true when two Decimal values are within tolerance."""

    return abs(left - right) <= tolerance


def validate_schema(
    document: Any,
    schema: dict[str, Any],
) -> list[str]:
    """Validate a document against JSON Schema."""

    errors: list[str] = []

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    for error in sorted(
        validator.iter_errors(document),
        key=lambda item: list(item.absolute_path),
    ):
        path = ".".join(str(part) for part in error.absolute_path)
        location = path or "<root>"

        errors.append(
            f"[schema-error] {location}: {error.message}"
        )

    return errors


def source_record_ids(document: dict[str, Any]) -> set[str]:
    """Return source record identifiers declared by the document."""

    source_context = document.get("source_context", {})

    return {
        str(record.get("record_id"))
        for record in source_context.get("source_records", [])
        if record.get("record_id")
    }


def validate_evidence_references(
    evidence_refs: list[dict[str, Any]],
    declared_source_ids: set[str],
    prefix: str,
) -> list[str]:
    """Validate evidence references against declared source records."""

    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    if not evidence_refs:
        errors.append(
            f"[semantic-error] {prefix}: "
            "at least one evidence reference is required"
        )
        return errors

    for index, evidence in enumerate(evidence_refs):
        evidence_prefix = f"{prefix}[{index}]"

        key = (
            str(evidence.get("record_type")),
            str(evidence.get("record_id")),
            str(evidence.get("relation")),
        )

        if key in seen:
            errors.append(
                f"[semantic-error] {evidence_prefix}: "
                f"duplicate evidence reference {key}"
            )

        seen.add(key)

        if evidence.get("verified") is not True:
            errors.append(
                f"[semantic-error] {evidence_prefix}.verified: "
                "evidence must be verified"
            )

        record_id = str(evidence.get("record_id"))

        if record_id not in declared_source_ids:
            errors.append(
                f"[semantic-error] {evidence_prefix}.record_id: "
                f"'{record_id}' is not declared in source_context"
            )

    return errors


# ---------------------------------------------------------------------------
# v0.1 — Allocation Ledger Record
# ---------------------------------------------------------------------------


def validate_allocation_ledger(
    document: dict[str, Any],
) -> list[str]:
    """Validate Allocation Ledger Record semantics."""

    errors: list[str] = []
    declared_source_ids = source_record_ids(document)
    beneficiary_ids: set[str] = set()

    calculated_gross = Decimal("0")
    calculated_payable = Decimal("0")
    calculated_held = Decimal("0")

    for index, beneficiary in enumerate(
        document.get("beneficiaries", [])
    ):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(beneficiary.get("beneficiary_id"))

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: "
                f"duplicate beneficiary '{beneficiary_id}'"
            )

        beneficiary_ids.add(beneficiary_id)

        gross = decimal_value(
            beneficiary.get("gross_allocation", 0),
            f"{prefix}.gross_allocation",
        )

        payable = decimal_value(
            beneficiary.get("payable_amount", 0),
            f"{prefix}.payable_amount",
        )

        held = decimal_value(
            beneficiary.get("held_amount", 0),
            f"{prefix}.held_amount",
        )

        calculated_gross += gross
        calculated_payable += payable
        calculated_held += held

        if gross != payable + held:
            errors.append(
                f"[semantic-error] {prefix}: gross_allocation must equal "
                f"payable_amount + held_amount "
                f"({gross} != {payable} + {held})"
            )

        errors.extend(
            validate_evidence_references(
                beneficiary.get("evidence_refs", []),
                declared_source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        hold_reasons = beneficiary.get("hold_reasons", [])
        allocation_status = beneficiary.get("allocation_status")

        if held > 0 and not hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "positive held_amount requires a hold reason"
            )

        if held == 0 and hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "hold reasons must not exist when held_amount is zero"
            )

        if held == 0 and payable > 0:
            if allocation_status != "payable":
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    "expected 'payable'"
                )

        if held > 0 and payable > 0:
            if allocation_status != "partially_held":
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    "expected 'partially_held'"
                )

        if held > 0 and payable == 0:
            if allocation_status != "fully_held":
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    "expected 'fully_held'"
                )

        if allocation_status == "rejected" and gross != 0:
            errors.append(
                f"[semantic-error] {prefix}: rejected allocation "
                "must have zero gross allocation"
            )

    totals = document.get("totals", {})
    pool = document.get("royalty_pool", {})

    declared_gross = decimal_value(
        totals.get("gross_allocated", 0),
        "totals.gross_allocated",
    )

    declared_payable = decimal_value(
        totals.get("payable_total", 0),
        "totals.payable_total",
    )

    declared_held = decimal_value(
        totals.get("held_total", 0),
        "totals.held_total",
    )

    unallocated = decimal_value(
        totals.get("unallocated_total", 0),
        "totals.unallocated_total",
    )

    rounding_adjustment = decimal_value(
        totals.get("rounding_adjustment", 0),
        "totals.rounding_adjustment",
    )

    distributable = decimal_value(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )

    gross_pool = decimal_value(
        pool.get("gross_amount", 0),
        "royalty_pool.gross_amount",
    )

    excluded = decimal_value(
        pool.get("excluded_amount", 0),
        "royalty_pool.excluded_amount",
    )

    if calculated_gross != declared_gross:
        errors.append(
            "[semantic-error] totals.gross_allocated: "
            f"declared {declared_gross}, calculated {calculated_gross}"
        )

    if calculated_payable != declared_payable:
        errors.append(
            "[semantic-error] totals.payable_total: "
            f"declared {declared_payable}, calculated {calculated_payable}"
        )

    if calculated_held != declared_held:
        errors.append(
            "[semantic-error] totals.held_total: "
            f"declared {declared_held}, calculated {calculated_held}"
        )

    if declared_gross != declared_payable + declared_held:
        errors.append(
            "[semantic-error] totals: gross_allocated must equal "
            "payable_total + held_total"
        )

    expected_distributable = (
        declared_gross
        + unallocated
        + rounding_adjustment
    )

    if distributable != expected_distributable:
        errors.append(
            "[semantic-error] royalty_pool.distributable_amount: "
            "must equal gross_allocated + unallocated_total "
            "+ rounding_adjustment"
        )

    if distributable > gross_pool:
        errors.append(
            "[semantic-error] royalty_pool.distributable_amount: "
            "must not exceed gross_amount"
        )

    if gross_pool != distributable + excluded:
        errors.append(
            "[semantic-error] royalty_pool: gross_amount must equal "
            "distributable_amount + excluded_amount"
        )

    errors.extend(
        validate_approval_state(
            document,
            status_field="ledger_status",
        )
    )

    errors.extend(
        validate_required_true_fields(
            document.get("safety_boundary", {}),
            [
                "evidence_required",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "human_approval_required",
            ],
            "safety_boundary",
        )
    )

    return errors


# ---------------------------------------------------------------------------
# v0.2 — Contribution Weight Resolution
# ---------------------------------------------------------------------------


def validate_contribution_weight_resolution(
    document: dict[str, Any],
) -> list[str]:
    """Validate Contribution Weight Resolution semantics."""

    errors: list[str] = []
    declared_source_ids = source_record_ids(document)
    beneficiary_ids: set[str] = set()

    method = document.get("resolution_method", {})
    precision = int(method.get("precision", 6))
    tolerance = Decimal("1").scaleb(-precision)
    normalization_target = decimal_value(
        method.get("normalization_target", 1),
        "resolution_method.normalization_target",
    )

    held_treatment = method.get("held_weight_treatment")

    calculated_component_total = Decimal("0")
    calculated_adjustment_total = Decimal("0")
    calculated_adjusted_total = Decimal("0")
    calculated_normalized_total = Decimal("0")

    included_count = 0
    held_count = 0
    excluded_count = 0

    eligible_adjusted_total = Decimal("0")
    beneficiary_values: list[
        tuple[int, str, Decimal, Decimal]
    ] = []

    for index, beneficiary in enumerate(
        document.get("beneficiaries", [])
    ):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(beneficiary.get("beneficiary_id"))
        status = str(beneficiary.get("resolution_status"))

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: "
                f"duplicate beneficiary '{beneficiary_id}'"
            )

        beneficiary_ids.add(beneficiary_id)

        attribution_refs = beneficiary.get("attribution_refs", [])

        for attribution_index, record_id in enumerate(attribution_refs):
            if record_id not in declared_source_ids:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.attribution_refs[{attribution_index}]: "
                    f"'{record_id}' is not declared in source_context"
                )

        component_sum = Decimal("0")

        for component_index, component in enumerate(
            beneficiary.get("components", [])
        ):
            component_prefix = (
                f"{prefix}.components[{component_index}]"
            )

            raw_score = decimal_value(
                component.get("raw_score", 0),
                f"{component_prefix}.raw_score",
            )

            multiplier = decimal_value(
                component.get("policy_multiplier", 0),
                f"{component_prefix}.policy_multiplier",
            )

            weighted_score = decimal_value(
                component.get("weighted_score", 0),
                f"{component_prefix}.weighted_score",
            )

            expected_weighted_score = raw_score * multiplier

            if not approximately_equal(
                weighted_score,
                expected_weighted_score,
                tolerance,
            ):
                errors.append(
                    f"[semantic-error] {component_prefix}.weighted_score: "
                    f"expected {expected_weighted_score}, "
                    f"found {weighted_score}"
                )

            component_sum += weighted_score

            errors.extend(
                validate_evidence_references(
                    component.get("evidence_refs", []),
                    declared_source_ids,
                    f"{component_prefix}.evidence_refs",
                )
            )

        declared_component_total = decimal_value(
            beneficiary.get("component_total", 0),
            f"{prefix}.component_total",
        )

        if not approximately_equal(
            component_sum,
            declared_component_total,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.component_total: "
                f"declared {declared_component_total}, "
                f"calculated {component_sum}"
            )

        adjustment_sum = Decimal("0")

        for adjustment_index, adjustment in enumerate(
            beneficiary.get("adjustments", [])
        ):
            adjustment_prefix = (
                f"{prefix}.adjustments[{adjustment_index}]"
            )

            delta_score = decimal_value(
                adjustment.get("delta_score", 0),
                f"{adjustment_prefix}.delta_score",
            )

            adjustment_sum += delta_score

            policy_ref = str(adjustment.get("policy_ref"))

            if policy_ref not in declared_source_ids:
                errors.append(
                    f"[semantic-error] {adjustment_prefix}.policy_ref: "
                    f"'{policy_ref}' is not declared in source_context"
                )

            errors.extend(
                validate_evidence_references(
                    adjustment.get("evidence_refs", []),
                    declared_source_ids,
                    f"{adjustment_prefix}.evidence_refs",
                )
            )

        adjusted_score = decimal_value(
            beneficiary.get("adjusted_score", 0),
            f"{prefix}.adjusted_score",
        )

        expected_adjusted_score = (
            declared_component_total + adjustment_sum
        )

        if not approximately_equal(
            adjusted_score,
            expected_adjusted_score,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.adjusted_score: "
                f"expected {expected_adjusted_score}, "
                f"found {adjusted_score}"
            )

        normalized_weight = decimal_value(
            beneficiary.get("normalized_weight", 0),
            f"{prefix}.normalized_weight",
        )

        errors.extend(
            validate_evidence_references(
                beneficiary.get("evidence_refs", []),
                declared_source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        hold_reasons = beneficiary.get("hold_reasons", [])
        exclusion_reasons = beneficiary.get("exclusion_reasons", [])

        if status == "included":
            included_count += 1

            if hold_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: "
                    "included beneficiary must not have hold reasons"
                )

            eligible_adjusted_total += adjusted_score

        elif status == "held_for_review":
            held_count += 1

            if not hold_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: "
                    "held beneficiary requires a hold reason"
                )

            if held_treatment == "reserve_in_normalization":
                eligible_adjusted_total += adjusted_score

        elif status == "excluded":
            excluded_count += 1

            if not exclusion_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.exclusion_reasons: "
                    "excluded beneficiary requires an exclusion reason"
                )

            if adjusted_score != 0:
                errors.append(
                    f"[semantic-error] {prefix}.adjusted_score: "
                    "excluded beneficiary must have zero adjusted score"
                )

            if normalized_weight != 0:
                errors.append(
                    f"[semantic-error] {prefix}.normalized_weight: "
                    "excluded beneficiary must have zero weight"
                )

        calculated_component_total += declared_component_total
        calculated_adjustment_total += adjustment_sum
        calculated_adjusted_total += adjusted_score
        calculated_normalized_total += normalized_weight

        beneficiary_values.append(
            (
                index,
                status,
                adjusted_score,
                normalized_weight,
            )
        )

    if eligible_adjusted_total <= 0:
        errors.append(
            "[semantic-error] beneficiaries: normalization requires "
            "a positive eligible adjusted score"
        )
    else:
        for (
            index,
            status,
            adjusted_score,
            normalized_weight,
        ) in beneficiary_values:
            prefix = f"beneficiaries[{index}]"

            eligible = (
                status == "included"
                or (
                    status == "held_for_review"
                    and held_treatment == "reserve_in_normalization"
                )
            )

            if eligible:
                expected_weight = (
                    adjusted_score / eligible_adjusted_total
                )

                if not approximately_equal(
                    normalized_weight,
                    expected_weight,
                    tolerance,
                ):
                    errors.append(
                        f"[semantic-error] "
                        f"{prefix}.normalized_weight: "
                        f"expected approximately {expected_weight}, "
                        f"found {normalized_weight}"
                    )

            elif status == "held_for_review":
                if normalized_weight != 0:
                    errors.append(
                        f"[semantic-error] "
                        f"{prefix}.normalized_weight: "
                        "held weight must be zero when held weights "
                        "are excluded from normalization"
                    )

    totals = document.get("totals", {})

    declared_component_total = decimal_value(
        totals.get("component_total", 0),
        "totals.component_total",
    )

    declared_adjustment_total = decimal_value(
        totals.get("adjustment_total", 0),
        "totals.adjustment_total",
    )

    declared_adjusted_total = decimal_value(
        totals.get("adjusted_score_total", 0),
        "totals.adjusted_score_total",
    )

    declared_normalized_total = decimal_value(
        totals.get("normalized_weight_total", 0),
        "totals.normalized_weight_total",
    )

    declared_residual = decimal_value(
        totals.get("normalization_residual", 0),
        "totals.normalization_residual",
    )

    total_checks = [
        (
            "totals.component_total",
            declared_component_total,
            calculated_component_total,
        ),
        (
            "totals.adjustment_total",
            declared_adjustment_total,
            calculated_adjustment_total,
        ),
        (
            "totals.adjusted_score_total",
            declared_adjusted_total,
            calculated_adjusted_total,
        ),
        (
            "totals.normalized_weight_total",
            declared_normalized_total,
            calculated_normalized_total,
        ),
    ]

    for field_name, declared, calculated in total_checks:
        if not approximately_equal(
            declared,
            calculated,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    expected_residual = (
        normalization_target - declared_normalized_total
    )

    if not approximately_equal(
        declared_residual,
        expected_residual,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.normalization_residual: "
            f"expected {expected_residual}, "
            f"found {declared_residual}"
        )

    if not approximately_equal(
        declared_normalized_total,
        normalization_target,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.normalized_weight_total: "
            f"must equal normalization target {normalization_target}"
        )

    count_checks = [
        (
            "totals.included_count",
            int(totals.get("included_count", 0)),
            included_count,
        ),
        (
            "totals.held_count",
            int(totals.get("held_count", 0)),
            held_count,
        ),
        (
            "totals.excluded_count",
            int(totals.get("excluded_count", 0)),
            excluded_count,
        ),
    ]

    for field_name, declared, calculated in count_checks:
        if declared != calculated:
            errors.append(
                f"[semantic-error] {field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    errors.extend(
        validate_approval_state(
            document,
            status_field="resolution_status",
        )
    )

    errors.extend(
        validate_required_true_fields(
            document.get("safety_boundary", {}),
            [
                "verified_attribution_required",
                "attribution_rewrite_prohibited",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "human_approval_required",
            ],
            "safety_boundary",
        )
    )

    return errors


# ---------------------------------------------------------------------------
# Shared validation
# ---------------------------------------------------------------------------


def validate_approval_state(
    document: dict[str, Any],
    status_field: str,
) -> list[str]:
    """Validate relationship between human approval and record status."""

    errors: list[str] = []

    approval_status = document.get("approval", {}).get("status")
    record_status = document.get(status_field)

    if approval_status == "pending":
        if record_status not in {
            "draft",
            "pending_human_approval",
        }:
            errors.append(
                f"[semantic-error] {status_field}: pending approval "
                "requires 'draft' or 'pending_human_approval'"
            )

    if approval_status == "approved":
        if record_status != "approved":
            errors.append(
                f"[semantic-error] {status_field}: approved human review "
                "requires status 'approved'"
            )

    if approval_status == "rejected":
        if record_status != "rejected":
            errors.append(
                f"[semantic-error] {status_field}: rejected human review "
                "requires status 'rejected'"
            )

    return errors


def validate_required_true_fields(
    record: dict[str, Any],
    field_names: list[str],
    prefix: str,
) -> list[str]:
    """Ensure mandatory safety fields remain true."""

    errors: list[str] = []

    for field_name in field_names:
        if record.get(field_name) is not True:
            errors.append(
                f"[semantic-error] {prefix}.{field_name}: must remain true"
            )

    return errors


def validate_target(target: ValidationTarget) -> list[str]:
    """Validate one schema and example target."""

    errors: list[str] = []

    if not target.schema_path.exists():
        return [
            f"[fatal] Schema not found: {target.schema_path}"
        ]

    if not target.example_path.exists():
        return [
            f"[fatal] Example not found: {target.example_path}"
        ]

    schema = load_document(target.schema_path)
    document = load_document(target.example_path)

    Draft202012Validator.check_schema(schema)

    schema_errors = validate_schema(document, schema)
    errors.extend(schema_errors)

    if not schema_errors:
        errors.extend(target.semantic_validator(document))

    return errors


def main() -> int:
    """Validate all specification examples."""

    targets = [
        ValidationTarget(
            name="Allocation Ledger Record",
            schema_path=(
                ROOT
                / "schemas"
                / "allocation-ledger-record.schema.json"
            ),
            example_path=(
                ROOT
                / "examples"
                / "pass"
                / "allocation-ledger-record.example.yaml"
            ),
            semantic_validator=validate_allocation_ledger,
        ),
        ValidationTarget(
            name="Contribution Weight Resolution",
            schema_path=(
                ROOT
                / "schemas"
                / "contribution-weight-resolution.schema.json"
            ),
            example_path=(
                ROOT
                / "examples"
                / "pass"
                / "contribution-weight-resolution.example.yaml"
            ),
            semantic_validator=(
                validate_contribution_weight_resolution
            ),
        ),
    ]

    print("=== Royalty Allocation Ledger Agent Validation ===")
    print()

    failed = False

    for target in targets:
        print(f"[validate] {target.name}")
        print(
            f"  schema : "
            f"{target.schema_path.relative_to(ROOT)}"
        )
        print(
            f"  example: "
            f"{target.example_path.relative_to(ROOT)}"
        )

        try:
            errors = validate_target(target)
        except Exception as error:
            errors = [f"[fatal] {error}"]

        if errors:
            failed = True

            for error in errors:
                print(error)
        else:
            print("[schema-ok]")
            print("[semantic-ok]")

        print()

    if failed:
        print("Validation failed.")
        return 1

    print("All Royalty Allocation Ledger Agent examples are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
