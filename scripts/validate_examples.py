#!/usr/bin/env python3
"""
Validate Royalty Allocation Ledger Agent examples.

Supported specifications:
- v0.1 Allocation Ledger Record
- v0.2 Contribution Weight Resolution
- v0.3 Multi-Beneficiary Allocation Plan
- v0.4 Dispute and Holdback Ledger

Validation layers:
1. JSON Schema validation
2. Cross-reference validation
3. Record-specific semantic validation
4. Approval and safety-boundary validation
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
)
from pathlib import Path
from typing import Any, Callable

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True)
class Target:
    """A schema/example pair and its semantic validator."""

    name: str
    schema: Path
    example: Path
    validate: Callable[[dict[str, Any]], list[str]]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def load(path: Path) -> Any:
    """Load a JSON or YAML document."""

    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        return json.loads(text)

    if path.suffix.lower() in {".yaml", ".yml"}:
        return yaml.safe_load(text)

    raise ValueError(f"Unsupported file type: {path.suffix}")


def schema_errors(
    document: Any,
    schema: dict[str, Any],
) -> list[str]:
    """Return JSON Schema validation errors."""

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors: list[str] = []

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


def decimal_value(
    value: Any,
    field_name: str,
) -> Decimal:
    """Convert a numeric field to Decimal."""

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be numeric: {value!r}"
        ) from error


def approximately_equal(
    left: Decimal,
    right: Decimal,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> bool:
    """Return whether two Decimal values are within tolerance."""

    return abs(left - right) <= tolerance


def declared_source_ids(
    document: dict[str, Any],
) -> set[str]:
    """Return source record IDs declared under source_context."""

    source_context = document.get("source_context", {})
    source_records = source_context.get("source_records", [])

    if not isinstance(source_records, list):
        return set()

    return {
        str(record["record_id"])
        for record in source_records
        if (
            isinstance(record, dict)
            and record.get("record_id")
        )
    }


def validate_evidence_refs(
    evidence_refs: Any,
    source_ids: set[str],
    prefix: str,
    *,
    required: bool = True,
) -> list[str]:
    """Validate evidence references and source-context membership."""

    errors: list[str] = []

    if not isinstance(evidence_refs, list):
        if required:
            errors.append(
                f"[semantic-error] {prefix}: must be an array"
            )
        return errors

    if required and not evidence_refs:
        errors.append(
            f"[semantic-error] {prefix}: "
            "at least one evidence reference is required"
        )
        return errors

    seen: set[tuple[str, str, str]] = set()

    for index, evidence in enumerate(evidence_refs):
        item_prefix = f"{prefix}[{index}]"

        if not isinstance(evidence, dict):
            errors.append(
                f"[semantic-error] {item_prefix}: "
                "must be an object"
            )
            continue

        record_type = str(evidence.get("record_type", ""))
        record_id = str(evidence.get("record_id", ""))
        relation = str(evidence.get("relation", ""))
        key = (record_type, record_id, relation)

        if key in seen:
            errors.append(
                f"[semantic-error] {item_prefix}: "
                f"duplicate evidence reference {key}"
            )

        seen.add(key)

        if evidence.get("verified") is not True:
            errors.append(
                f"[semantic-error] {item_prefix}.verified: "
                "must be true"
            )

        if record_id not in source_ids:
            errors.append(
                f"[semantic-error] {item_prefix}.record_id: "
                f"'{record_id}' is not declared in source_context"
            )

    return errors


def validate_required_true_fields(
    record: Any,
    field_names: list[str],
    prefix: str,
) -> list[str]:
    """Ensure mandatory control fields remain true."""

    if not isinstance(record, dict):
        return [
            f"[semantic-error] {prefix}: must be an object"
        ]

    errors: list[str] = []

    for field_name in field_names:
        if record.get(field_name) is not True:
            errors.append(
                f"[semantic-error] {prefix}.{field_name}: "
                "must remain true"
            )

    return errors


def validate_approval_state(
    document: dict[str, Any],
    status_field: str,
) -> list[str]:
    """Validate approval status against the record status."""

    approval = document.get("approval", {})
    approval_status = (
        approval.get("status")
        if isinstance(approval, dict)
        else None
    )
    record_status = document.get(status_field)

    errors: list[str] = []

    if approval_status == "pending":
        if record_status not in {
            "draft",
            "pending_human_approval",
        }:
            errors.append(
                f"[semantic-error] {status_field}: "
                "pending approval requires 'draft' or "
                "'pending_human_approval'"
            )

    elif approval_status == "approved":
        if record_status != "approved":
            errors.append(
                f"[semantic-error] {status_field}: "
                "approved human review requires 'approved'"
            )

    elif approval_status == "rejected":
        if record_status != "rejected":
            errors.append(
                f"[semantic-error] {status_field}: "
                "rejected human review requires 'rejected'"
            )

    return errors


def register_unique(
    value: str,
    seen: set[str],
    prefix: str,
    label: str,
) -> list[str]:
    """Register an identifier and report duplicates."""

    if value in seen:
        return [
            f"[semantic-error] {prefix}: "
            f"duplicate {label} '{value}'"
        ]

    seen.add(value)
    return []


# ---------------------------------------------------------------------------
# v0.1 — Allocation Ledger Record
# ---------------------------------------------------------------------------


def validate_v01(
    document: dict[str, Any],
) -> list[str]:
    """Validate Allocation Ledger Record semantics."""

    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    gross_sum = Decimal("0")
    payable_sum = Decimal("0")
    held_sum = Decimal("0")

    beneficiaries = document.get("beneficiaries", [])

    if not isinstance(beneficiaries, list):
        return [
            "[semantic-error] beneficiaries: must be an array"
        ]

    for index, beneficiary in enumerate(beneficiaries):
        prefix = f"beneficiaries[{index}]"

        if not isinstance(beneficiary, dict):
            errors.append(
                f"[semantic-error] {prefix}: must be an object"
            )
            continue

        beneficiary_id = str(
            beneficiary.get("beneficiary_id", "")
        )

        errors.extend(
            register_unique(
                beneficiary_id,
                beneficiary_ids,
                f"{prefix}.beneficiary_id",
                "beneficiary",
            )
        )

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

        gross_sum += gross
        payable_sum += payable
        held_sum += held

        if gross != payable + held:
            errors.append(
                f"[semantic-error] {prefix}: "
                "gross_allocation must equal "
                "payable_amount + held_amount"
            )

        errors.extend(
            validate_evidence_refs(
                beneficiary.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        hold_reasons = beneficiary.get("hold_reasons", [])
        allocation_status = beneficiary.get(
            "allocation_status"
        )

        if held > 0 and not hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "positive held_amount requires a hold reason"
            )

        if held == 0 and hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "must be absent when held_amount is zero"
            )

        expected_status: str | None = None

        if payable > 0 and held == 0:
            expected_status = "payable"
        elif payable > 0 and held > 0:
            expected_status = "partially_held"
        elif payable == 0 and held > 0:
            expected_status = "fully_held"

        if (
            expected_status is not None
            and allocation_status != expected_status
        ):
            errors.append(
                f"[semantic-error] {prefix}.allocation_status: "
                f"expected '{expected_status}'"
            )

        if (
            allocation_status == "rejected"
            and gross != 0
        ):
            errors.append(
                f"[semantic-error] {prefix}: "
                "rejected allocation must have zero gross amount"
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

    gross_pool = decimal_value(
        pool.get("gross_amount", 0),
        "royalty_pool.gross_amount",
    )
    distributable = decimal_value(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )
    excluded_amount = decimal_value(
        pool.get("excluded_amount", 0),
        "royalty_pool.excluded_amount",
    )

    if gross_sum != declared_gross:
        errors.append(
            "[semantic-error] totals.gross_allocated: "
            f"declared {declared_gross}, calculated {gross_sum}"
        )

    if payable_sum != declared_payable:
        errors.append(
            "[semantic-error] totals.payable_total: "
            f"declared {declared_payable}, calculated {payable_sum}"
        )

    if held_sum != declared_held:
        errors.append(
            "[semantic-error] totals.held_total: "
            f"declared {declared_held}, calculated {held_sum}"
        )

    if declared_gross != declared_payable + declared_held:
        errors.append(
            "[semantic-error] totals: "
            "gross_allocated must equal payable_total + held_total"
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

    if gross_pool != distributable + excluded_amount:
        errors.append(
            "[semantic-error] royalty_pool: "
            "gross_amount must equal "
            "distributable_amount + excluded_amount"
        )

    errors.extend(
        validate_approval_state(
            document,
            "ledger_status",
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


def validate_v02(
    document: dict[str, Any],
) -> list[str]:
    """Validate Contribution Weight Resolution semantics."""

    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    method = document.get("resolution_method", {})
    precision = int(method.get("precision", 6))
    tolerance = Decimal("1").scaleb(-precision)
    normalization_target = decimal_value(
        method.get("normalization_target", 1),
        "resolution_method.normalization_target",
    )
    held_treatment = method.get(
        "held_weight_treatment"
    )

    component_total = Decimal("0")
    adjustment_total = Decimal("0")
    adjusted_total = Decimal("0")
    normalized_total = Decimal("0")
    eligible_total = Decimal("0")

    included_count = 0
    held_count = 0
    excluded_count = 0

    beneficiary_values: list[
        tuple[int, str, Decimal, Decimal]
    ] = []

    for index, beneficiary in enumerate(
        document.get("beneficiaries", [])
    ):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(
            beneficiary.get("beneficiary_id", "")
        )

        errors.extend(
            register_unique(
                beneficiary_id,
                beneficiary_ids,
                f"{prefix}.beneficiary_id",
                "beneficiary",
            )
        )

        for ref_index, record_id in enumerate(
            beneficiary.get("attribution_refs", [])
        ):
            if str(record_id) not in source_ids:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.attribution_refs[{ref_index}]: "
                    f"'{record_id}' is not declared in source_context"
                )

        beneficiary_component_total = Decimal("0")

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

            expected_weighted = raw_score * multiplier

            if not approximately_equal(
                weighted_score,
                expected_weighted,
                tolerance,
            ):
                errors.append(
                    f"[semantic-error] "
                    f"{component_prefix}.weighted_score: "
                    f"expected {expected_weighted}, "
                    f"found {weighted_score}"
                )

            beneficiary_component_total += weighted_score

            errors.extend(
                validate_evidence_refs(
                    component.get("evidence_refs", []),
                    source_ids,
                    f"{component_prefix}.evidence_refs",
                )
            )

        declared_component_total = decimal_value(
            beneficiary.get("component_total", 0),
            f"{prefix}.component_total",
        )

        if not approximately_equal(
            declared_component_total,
            beneficiary_component_total,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.component_total: "
                f"declared {declared_component_total}, "
                f"calculated {beneficiary_component_total}"
            )

        beneficiary_adjustment_total = Decimal("0")

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
            beneficiary_adjustment_total += delta_score

            policy_ref = str(
                adjustment.get("policy_ref", "")
            )

            if policy_ref not in source_ids:
                errors.append(
                    f"[semantic-error] "
                    f"{adjustment_prefix}.policy_ref: "
                    f"'{policy_ref}' is not declared in source_context"
                )

            errors.extend(
                validate_evidence_refs(
                    adjustment.get("evidence_refs", []),
                    source_ids,
                    f"{adjustment_prefix}.evidence_refs",
                )
            )

        adjusted_score = decimal_value(
            beneficiary.get("adjusted_score", 0),
            f"{prefix}.adjusted_score",
        )

        expected_adjusted = (
            declared_component_total
            + beneficiary_adjustment_total
        )

        if not approximately_equal(
            adjusted_score,
            expected_adjusted,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.adjusted_score: "
                f"expected {expected_adjusted}, "
                f"found {adjusted_score}"
            )

        normalized_weight = decimal_value(
            beneficiary.get("normalized_weight", 0),
            f"{prefix}.normalized_weight",
        )

        errors.extend(
            validate_evidence_refs(
                beneficiary.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        status = str(
            beneficiary.get("resolution_status", "")
        )

        if status == "included":
            included_count += 1
            eligible_total += adjusted_score

            if beneficiary.get("hold_reasons"):
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: "
                    "included beneficiary must not have hold reasons"
                )

        elif status == "held_for_review":
            held_count += 1

            if not beneficiary.get("hold_reasons"):
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: "
                    "held beneficiary requires a hold reason"
                )

            if held_treatment == "reserve_in_normalization":
                eligible_total += adjusted_score

        elif status == "excluded":
            excluded_count += 1

            if not beneficiary.get("exclusion_reasons"):
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.exclusion_reasons: "
                    "excluded beneficiary requires a reason"
                )

            if adjusted_score != 0:
                errors.append(
                    f"[semantic-error] {prefix}.adjusted_score: "
                    "excluded beneficiary must have zero score"
                )

            if normalized_weight != 0:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.normalized_weight: "
                    "excluded beneficiary must have zero weight"
                )

        component_total += declared_component_total
        adjustment_total += beneficiary_adjustment_total
        adjusted_total += adjusted_score
        normalized_total += normalized_weight

        beneficiary_values.append(
            (
                index,
                status,
                adjusted_score,
                normalized_weight,
            )
        )

    if eligible_total <= 0:
        errors.append(
            "[semantic-error] beneficiaries: "
            "eligible adjusted score must be positive"
        )
    else:
        for (
            index,
            status,
            adjusted_score,
            normalized_weight,
        ) in beneficiary_values:
            eligible = (
                status == "included"
                or (
                    status == "held_for_review"
                    and held_treatment
                    == "reserve_in_normalization"
                )
            )

            if eligible:
                expected_weight = (
                    adjusted_score / eligible_total
                )

                if not approximately_equal(
                    normalized_weight,
                    expected_weight,
                    tolerance,
                ):
                    errors.append(
                        f"[semantic-error] "
                        f"beneficiaries[{index}].normalized_weight: "
                        f"expected approximately {expected_weight}, "
                        f"found {normalized_weight}"
                    )

            elif (
                status == "held_for_review"
                and normalized_weight != 0
            ):
                errors.append(
                    f"[semantic-error] "
                    f"beneficiaries[{index}].normalized_weight: "
                    "must be zero when held weights are excluded"
                )

    totals = document.get("totals", {})

    total_checks = [
        ("component_total", component_total),
        ("adjustment_total", adjustment_total),
        ("adjusted_score_total", adjusted_total),
        ("normalized_weight_total", normalized_total),
    ]

    for field_name, calculated in total_checks:
        declared = decimal_value(
            totals.get(field_name, 0),
            f"totals.{field_name}",
        )

        if not approximately_equal(
            declared,
            calculated,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    declared_normalized_total = decimal_value(
        totals.get("normalized_weight_total", 0),
        "totals.normalized_weight_total",
    )
    declared_residual = decimal_value(
        totals.get("normalization_residual", 0),
        "totals.normalization_residual",
    )
    expected_residual = (
        normalization_target
        - declared_normalized_total
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
            f"must equal normalization target "
            f"{normalization_target}"
        )

    count_checks = [
        ("included_count", included_count),
        ("held_count", held_count),
        ("excluded_count", excluded_count),
    ]

    for field_name, calculated in count_checks:
        declared = int(totals.get(field_name, 0))

        if declared != calculated:
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    errors.extend(
        validate_approval_state(
            document,
            "resolution_status",
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
# v0.3 — Multi-Beneficiary Allocation Plan
# ---------------------------------------------------------------------------


def rounding_mode(method: str) -> str:
    """Map a policy rounding name to Decimal rounding mode."""

    modes = {
        "half_up": ROUND_HALF_UP,
        "half_even": ROUND_HALF_EVEN,
        "floor": ROUND_FLOOR,
        "ceiling": ROUND_CEILING,
    }

    if method not in modes:
        raise ValueError(
            f"Unsupported rounding method: {method}"
        )

    return modes[method]


def rounded_value(
    value: Decimal,
    decimal_places: int,
    method: str,
) -> Decimal:
    """Round a value using the declared allocation policy."""

    quantum = Decimal("1").scaleb(-decimal_places)

    return value.quantize(
        quantum,
        rounding=rounding_mode(method),
    )


def validate_v03(
    document: dict[str, Any],
) -> list[str]:
    """Validate Multi-Beneficiary Allocation Plan semantics."""

    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    source_context = document.get("source_context", {})
    weight_resolution_id = str(
        source_context.get("weight_resolution_id", "")
    )

    policy = document.get("policy_application", {})
    rounding_policy = policy.get(
        "rounding_policy",
        {},
    )
    rounding_method_name = str(
        rounding_policy.get("method", "half_up")
    )
    decimal_places = int(
        rounding_policy.get("decimal_places", 0)
    )
    tolerance = Decimal("1").scaleb(
        -(decimal_places + 4)
    )

    fixed_total = Decimal("0")
    proportional_total = Decimal("0")
    final_total = Decimal("0")
    payable_total = Decimal("0")
    reserved_total = Decimal("0")
    proportional_weight_total = Decimal("0")

    for index, beneficiary in enumerate(
        document.get("beneficiaries", [])
    ):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(
            beneficiary.get("beneficiary_id", "")
        )

        errors.extend(
            register_unique(
                beneficiary_id,
                beneficiary_ids,
                f"{prefix}.beneficiary_id",
                "beneficiary",
            )
        )

        mode = str(
            beneficiary.get("allocation_mode", "")
        )
        state = str(
            beneficiary.get("plan_state", "")
        )
        calculation = beneficiary.get(
            "calculation",
            {},
        )

        basis_amount = decimal_value(
            calculation.get("basis_amount", 0),
            f"{prefix}.calculation.basis_amount",
        )
        raw_amount = decimal_value(
            calculation.get("raw_amount", 0),
            f"{prefix}.calculation.raw_amount",
        )
        constraint_adjustment = decimal_value(
            calculation.get("constraint_adjustment", 0),
            f"{prefix}.calculation.constraint_adjustment",
        )
        declared_rounded = decimal_value(
            calculation.get("rounded_amount", 0),
            f"{prefix}.calculation.rounded_amount",
        )
        remainder_adjustment = decimal_value(
            calculation.get("remainder_adjustment", 0),
            f"{prefix}.calculation.remainder_adjustment",
        )
        final_amount = decimal_value(
            calculation.get("final_planned_amount", 0),
            f"{prefix}.calculation.final_planned_amount",
        )

        expected_raw: Decimal | None = None

        if mode == "fixed_amount":
            expected_raw = decimal_value(
                calculation.get("fixed_amount", 0),
                f"{prefix}.calculation.fixed_amount",
            )

        elif mode == "fixed_rate":
            fixed_rate = decimal_value(
                calculation.get("fixed_rate", 0),
                f"{prefix}.calculation.fixed_rate",
            )
            expected_raw = basis_amount * fixed_rate

        elif mode in {
            "proportional_weight",
            "pooled_weight",
        }:
            normalized_weight = decimal_value(
                calculation.get("normalized_weight", 0),
                f"{prefix}.calculation.normalized_weight",
            )
            source_weight = beneficiary.get(
                "source_weight_ref",
                {},
            )
            source_resolution_id = str(
                source_weight.get("resolution_id", "")
            )
            source_beneficiary_id = str(
                source_weight.get("beneficiary_id", "")
            )
            source_status = str(
                source_weight.get("resolution_status", "")
            )
            source_normalized_weight = decimal_value(
                source_weight.get("normalized_weight", 0),
                (
                    f"{prefix}.source_weight_ref."
                    "normalized_weight"
                ),
            )

            if source_resolution_id != weight_resolution_id:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.source_weight_ref.resolution_id: "
                    "must match source_context.weight_resolution_id"
                )

            if source_beneficiary_id != beneficiary_id:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.source_weight_ref.beneficiary_id: "
                    "must match beneficiary_id"
                )

            if not approximately_equal(
                normalized_weight,
                source_normalized_weight,
                tolerance,
            ):
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.calculation.normalized_weight: "
                    "must match source_weight_ref.normalized_weight"
                )

            if (
                source_status == "held_for_review"
                and state != "reserved_for_review"
            ):
                errors.append(
                    f"[semantic-error] {prefix}.plan_state: "
                    "held source weight must remain reserved"
                )

            expected_raw = (
                basis_amount * normalized_weight
            )
            proportional_weight_total += (
                normalized_weight
            )

        elif mode == "remainder_assignment":
            expected_raw = raw_amount

        if (
            expected_raw is not None
            and not approximately_equal(
                raw_amount,
                expected_raw,
                tolerance,
            )
        ):
            errors.append(
                f"[semantic-error] "
                f"{prefix}.calculation.raw_amount: "
                f"expected {expected_raw}, found {raw_amount}"
            )

        constrained_amount = (
            raw_amount + constraint_adjustment
        )

        minimum_amount = calculation.get(
            "minimum_amount"
        )
        maximum_amount = calculation.get(
            "maximum_amount"
        )

        if minimum_amount is not None:
            minimum = decimal_value(
                minimum_amount,
                f"{prefix}.calculation.minimum_amount",
            )

            if constrained_amount < minimum:
                errors.append(
                    f"[semantic-error] {prefix}.calculation: "
                    "amount remains below minimum_amount"
                )

        if maximum_amount is not None:
            maximum = decimal_value(
                maximum_amount,
                f"{prefix}.calculation.maximum_amount",
            )

            if constrained_amount > maximum:
                errors.append(
                    f"[semantic-error] {prefix}.calculation: "
                    "amount exceeds maximum_amount"
                )

        expected_rounded = rounded_value(
            constrained_amount,
            decimal_places,
            rounding_method_name,
        )

        if not approximately_equal(
            declared_rounded,
            expected_rounded,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] "
                f"{prefix}.calculation.rounded_amount: "
                f"expected {expected_rounded}, "
                f"found {declared_rounded}"
            )

        expected_final = (
            declared_rounded
            + remainder_adjustment
        )

        if not approximately_equal(
            final_amount,
            expected_final,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] "
                f"{prefix}.calculation.final_planned_amount: "
                "must equal rounded_amount + remainder_adjustment"
            )

        if state == "reserved_for_review":
            if not beneficiary.get("reserve_reasons"):
                errors.append(
                    f"[semantic-error] {prefix}.reserve_reasons: "
                    "reserved allocation requires a reason"
                )

            reserved_total += final_amount

        elif state == "planned_payable":
            payable_total += final_amount

        elif state == "excluded":
            if final_amount != 0:
                errors.append(
                    f"[semantic-error] {prefix}: "
                    "excluded allocation must have zero final amount"
                )

        errors.extend(
            validate_evidence_refs(
                beneficiary.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        if mode in {
            "fixed_amount",
            "fixed_rate",
            "remainder_assignment",
        }:
            fixed_total += final_amount

        elif mode in {
            "proportional_weight",
            "pooled_weight",
        }:
            proportional_total += final_amount

        final_total += final_amount

    if not approximately_equal(
        proportional_weight_total,
        Decimal("1"),
        tolerance,
    ):
        errors.append(
            "[semantic-error] beneficiaries: "
            "proportional normalized weights must total 1.0"
        )

    totals = document.get("totals", {})
    pool = document.get("royalty_pool", {})

    declared_fixed = decimal_value(
        totals.get("fixed_allocation_total", 0),
        "totals.fixed_allocation_total",
    )
    declared_proportional_pool = decimal_value(
        totals.get("proportional_pool_amount", 0),
        "totals.proportional_pool_amount",
    )
    declared_proportional = decimal_value(
        totals.get("proportional_allocation_total", 0),
        "totals.proportional_allocation_total",
    )
    declared_final = decimal_value(
        totals.get("final_plan_total", 0),
        "totals.final_plan_total",
    )
    declared_payable = decimal_value(
        totals.get("payable_candidate_total", 0),
        "totals.payable_candidate_total",
    )
    declared_reserved = decimal_value(
        totals.get("reserved_total", 0),
        "totals.reserved_total",
    )
    unallocated = decimal_value(
        totals.get("unallocated_total", 0),
        "totals.unallocated_total",
    )
    rounding_residual = decimal_value(
        totals.get("rounding_residual", 0),
        "totals.rounding_residual",
    )
    distributable = decimal_value(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )

    calculated_checks = [
        (
            "fixed_allocation_total",
            declared_fixed,
            fixed_total,
        ),
        (
            "proportional_allocation_total",
            declared_proportional,
            proportional_total,
        ),
        (
            "final_plan_total",
            declared_final,
            final_total,
        ),
        (
            "payable_candidate_total",
            declared_payable,
            payable_total,
        ),
        (
            "reserved_total",
            declared_reserved,
            reserved_total,
        ),
    ]

    for field_name, declared, calculated in (
        calculated_checks
    ):
        if not approximately_equal(
            declared,
            calculated,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    policy_fixed = decimal_value(
        policy.get("fixed_allocation_total", 0),
        "policy_application.fixed_allocation_total",
    )
    policy_proportional = decimal_value(
        policy.get("proportional_pool_amount", 0),
        "policy_application.proportional_pool_amount",
    )

    if not approximately_equal(
        declared_fixed,
        policy_fixed,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.fixed_allocation_total: "
            "must match policy_application.fixed_allocation_total"
        )

    if not approximately_equal(
        declared_proportional_pool,
        policy_proportional,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.proportional_pool_amount: "
            "must match policy_application.proportional_pool_amount"
        )

    if not approximately_equal(
        declared_proportional,
        declared_proportional_pool,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.proportional_allocation_total: "
            "must equal proportional_pool_amount "
            "after remainder handling"
        )

    if not approximately_equal(
        declared_final,
        declared_fixed + declared_proportional,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.final_plan_total: "
            "must equal fixed + proportional allocations"
        )

    if not approximately_equal(
        declared_final,
        declared_payable + declared_reserved,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.final_plan_total: "
            "must equal payable_candidate_total + reserved_total"
        )

    expected_residual = (
        distributable
        - declared_final
        - unallocated
    )

    if not approximately_equal(
        rounding_residual,
        expected_residual,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.rounding_residual: "
            f"expected {expected_residual}, "
            f"found {rounding_residual}"
        )

    if not approximately_equal(
        distributable,
        declared_final
        + unallocated
        + rounding_residual,
        tolerance,
    ):
        errors.append(
            "[semantic-error] royalty_pool.distributable_amount: "
            "must equal final plan + unallocated + residual"
        )

    errors.extend(
        validate_approval_state(
            document,
            "plan_status",
        )
    )

    errors.extend(
        validate_required_true_fields(
            document.get("safety_boundary", {}),
            [
                "approved_weight_resolution_required",
                "evidence_required",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "held_weight_redistribution_prohibited",
                "human_approval_required",
            ],
            "safety_boundary",
        )
    )

    return errors


# ---------------------------------------------------------------------------
# v0.4 — Dispute and Holdback Ledger
# ---------------------------------------------------------------------------


def validate_v04(
    document: dict[str, Any],
) -> list[str]:
    """Validate Dispute and Holdback Ledger semantics."""

    errors: list[str] = []
    source_ids = declared_source_ids(document)

    source_context = document.get("source_context", {})
    source_plan_id = str(
        source_context.get("allocation_plan_id", "")
    )

    dispute_ids: set[str] = set()
    dispute_records: dict[str, dict[str, Any]] = {}
    affected_beneficiary_ids: set[str] = set()

    open_statuses = {
        "open",
        "evidence_requested",
        "under_review",
        "partially_resolved",
        "expired",
    }
    resolved_statuses = {
        "resolved",
        "rejected",
    }

    open_dispute_count = 0
    resolved_dispute_count = 0

    for index, dispute in enumerate(
        document.get("dispute_cases", [])
    ):
        prefix = f"dispute_cases[{index}]"

        dispute_id = str(
            dispute.get("dispute_id", "")
        )
        beneficiary_id = str(
            dispute.get(
                "affected_beneficiary_id",
                "",
            )
        )

        errors.extend(
            register_unique(
                dispute_id,
                dispute_ids,
                f"{prefix}.dispute_id",
                "dispute",
            )
        )

        dispute_records[dispute_id] = dispute
        affected_beneficiary_ids.add(
            beneficiary_id
        )

        allocation_ref = dispute.get(
            "affected_allocation_ref",
            {},
        )
        referenced_plan_id = str(
            allocation_ref.get("plan_id", "")
        )
        referenced_beneficiary_id = str(
            allocation_ref.get("beneficiary_id", "")
        )
        original_reserved = decimal_value(
            allocation_ref.get(
                "original_reserved_amount",
                0,
            ),
            (
                f"{prefix}.affected_allocation_ref."
                "original_reserved_amount"
            ),
        )

        if referenced_plan_id != source_plan_id:
            errors.append(
                f"[semantic-error] "
                f"{prefix}.affected_allocation_ref.plan_id: "
                "must match source_context.allocation_plan_id"
            )

        if referenced_beneficiary_id != beneficiary_id:
            errors.append(
                f"[semantic-error] "
                f"{prefix}.affected_allocation_ref.beneficiary_id: "
                "must match affected_beneficiary_id"
            )

        dispute_scope = dispute.get(
            "dispute_scope",
            {},
        )
        disputed_amount = decimal_value(
            dispute_scope.get("disputed_amount", 0),
            f"{prefix}.dispute_scope.disputed_amount",
        )
        undisputed_amount = decimal_value(
            dispute_scope.get("undisputed_amount", 0),
            f"{prefix}.dispute_scope.undisputed_amount",
        )

        if original_reserved != (
            disputed_amount + undisputed_amount
        ):
            errors.append(
                f"[semantic-error] {prefix}.dispute_scope: "
                "disputed_amount + undisputed_amount must equal "
                "original_reserved_amount"
            )

        status = str(dispute.get("status", ""))

        if status in open_statuses:
            open_dispute_count += 1

        if status in resolved_statuses:
            resolved_dispute_count += 1

        resolution = dispute.get("resolution")

        if status in {
            "partially_resolved",
            "resolved",
            "rejected",
        }:
            if not isinstance(resolution, dict):
                errors.append(
                    f"[semantic-error] {prefix}.resolution: "
                    "required for the current status"
                )
            else:
                released = decimal_value(
                    resolution.get("released_amount", 0),
                    f"{prefix}.resolution.released_amount",
                )
                continued = decimal_value(
                    resolution.get(
                        "continued_hold_amount",
                        0,
                    ),
                    (
                        f"{prefix}.resolution."
                        "continued_hold_amount"
                    ),
                )
                returned = decimal_value(
                    resolution.get(
                        "returned_to_pool_amount",
                        0,
                    ),
                    (
                        f"{prefix}.resolution."
                        "returned_to_pool_amount"
                    ),
                )

                if original_reserved != (
                    released
                    + continued
                    + returned
                ):
                    errors.append(
                        f"[semantic-error] {prefix}.resolution: "
                        "released + continued hold + returned "
                        "must equal original reserved amount"
                    )

        errors.extend(
            validate_evidence_refs(
                dispute.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

    holdback_ids: set[str] = set()

    source_reserved_total = Decimal("0")
    correction_adjustment_total = Decimal("0")
    effective_holdback_total = Decimal("0")
    released_total = Decimal("0")
    current_held_total = Decimal("0")
    returned_to_pool_total = Decimal("0")

    for index, holdback in enumerate(
        document.get("holdback_entries", [])
    ):
        prefix = f"holdback_entries[{index}]"

        holdback_id = str(
            holdback.get("holdback_id", "")
        )
        dispute_id = str(
            holdback.get("dispute_id", "")
        )
        beneficiary_id = str(
            holdback.get("beneficiary_id", "")
        )

        errors.extend(
            register_unique(
                holdback_id,
                holdback_ids,
                f"{prefix}.holdback_id",
                "holdback",
            )
        )

        dispute = dispute_records.get(dispute_id)

        if dispute is None:
            errors.append(
                f"[semantic-error] {prefix}.dispute_id: "
                f"unknown dispute '{dispute_id}'"
            )
        elif beneficiary_id != str(
            dispute.get(
                "affected_beneficiary_id",
                "",
            )
        ):
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: "
                "must match the dispute beneficiary"
            )

        if str(
            holdback.get("source_plan_id", "")
        ) != source_plan_id:
            errors.append(
                f"[semantic-error] {prefix}.source_plan_id: "
                "must match source_context.allocation_plan_id"
            )

        source_reserved = decimal_value(
            holdback.get("source_reserved_amount", 0),
            f"{prefix}.source_reserved_amount",
        )
        correction_adjustment = decimal_value(
            holdback.get("correction_adjustment", 0),
            f"{prefix}.correction_adjustment",
        )
        effective_holdback = decimal_value(
            holdback.get(
                "effective_holdback_amount",
                0,
            ),
            f"{prefix}.effective_holdback_amount",
        )
        released = decimal_value(
            holdback.get("released_amount", 0),
            f"{prefix}.released_amount",
        )
        current_held = decimal_value(
            holdback.get("current_held_amount", 0),
            f"{prefix}.current_held_amount",
        )
        returned = decimal_value(
            holdback.get(
                "returned_to_pool_amount",
                0,
            ),
            f"{prefix}.returned_to_pool_amount",
        )

        if effective_holdback != (
            source_reserved
            + correction_adjustment
        ):
            errors.append(
                f"[semantic-error] "
                f"{prefix}.effective_holdback_amount: "
                "must equal source_reserved_amount + "
                "correction_adjustment"
            )

        if effective_holdback != (
            released
            + current_held
            + returned
        ):
            errors.append(
                f"[semantic-error] {prefix}: "
                "effective holdback must equal released + "
                "currently held + returned to pool"
            )

        status = str(holdback.get("status", ""))

        if (
            status == "active_hold"
            and current_held <= 0
        ):
            errors.append(
                f"[semantic-error] {prefix}.status: "
                "active_hold requires positive current_held_amount"
            )

        elif status == "partial_release":
            if released <= 0 or current_held <= 0:
                errors.append(
                    f"[semantic-error] {prefix}.status: "
                    "partial_release requires released and held amounts"
                )

        elif status == "fully_released":
            if current_held != 0 or released <= 0:
                errors.append(
                    f"[semantic-error] {prefix}.status: "
                    "fully_released requires zero hold and release"
                )

        elif status == "returned_to_pool":
            if current_held != 0 or returned <= 0:
                errors.append(
                    f"[semantic-error] {prefix}.status: "
                    "returned_to_pool requires zero hold and return"
                )

        release_event_total = Decimal("0")
        pool_return_event_total = Decimal("0")

        for event_index, event in enumerate(
            holdback.get("release_events", [])
        ):
            event_prefix = (
                f"{prefix}.release_events[{event_index}]"
            )
            event_amount = decimal_value(
                event.get("amount", 0),
                f"{event_prefix}.amount",
            )
            destination = event.get("destination")

            if destination == "beneficiary_allocation":
                release_event_total += event_amount

            elif destination == "unallocated_pool":
                pool_return_event_total += event_amount

            errors.extend(
                validate_evidence_refs(
                    event.get("evidence_refs", []),
                    source_ids,
                    f"{event_prefix}.evidence_refs",
                )
            )

        if release_event_total != released:
            errors.append(
                f"[semantic-error] {prefix}.release_events: "
                "beneficiary release events must equal released_amount"
            )

        if pool_return_event_total != returned:
            errors.append(
                f"[semantic-error] {prefix}.release_events: "
                "pool return events must equal returned_to_pool_amount"
            )

        errors.extend(
            validate_evidence_refs(
                holdback.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        if dispute is not None:
            resolution = dispute.get("resolution")

            if isinstance(resolution, dict):
                resolution_released = decimal_value(
                    resolution.get("released_amount", 0),
                    (
                        f"dispute {dispute_id}."
                        "resolution.released_amount"
                    ),
                )
                resolution_held = decimal_value(
                    resolution.get(
                        "continued_hold_amount",
                        0,
                    ),
                    (
                        f"dispute {dispute_id}."
                        "resolution.continued_hold_amount"
                    ),
                )
                resolution_returned = decimal_value(
                    resolution.get(
                        "returned_to_pool_amount",
                        0,
                    ),
                    (
                        f"dispute {dispute_id}."
                        "resolution.returned_to_pool_amount"
                    ),
                )

                if released != resolution_released:
                    errors.append(
                        f"[semantic-error] "
                        f"{prefix}.released_amount: "
                        "must match dispute resolution"
                    )

                if current_held != resolution_held:
                    errors.append(
                        f"[semantic-error] "
                        f"{prefix}.current_held_amount: "
                        "must match dispute resolution"
                    )

                if returned != resolution_returned:
                    errors.append(
                        f"[semantic-error] "
                        f"{prefix}.returned_to_pool_amount: "
                        "must match dispute resolution"
                    )

        source_reserved_total += source_reserved
        correction_adjustment_total += (
            correction_adjustment
        )
        effective_holdback_total += effective_holdback
        released_total += released
        current_held_total += current_held
        returned_to_pool_total += returned

    totals = document.get("totals", {})

    total_checks = [
        (
            "source_reserved_total",
            source_reserved_total,
        ),
        (
            "correction_adjustment_total",
            correction_adjustment_total,
        ),
        (
            "effective_holdback_total",
            effective_holdback_total,
        ),
        (
            "released_to_allocation_total",
            released_total,
        ),
        (
            "current_held_total",
            current_held_total,
        ),
        (
            "returned_to_pool_total",
            returned_to_pool_total,
        ),
    ]

    for field_name, calculated in total_checks:
        declared = decimal_value(
            totals.get(field_name, 0),
            f"totals.{field_name}",
        )

        if declared != calculated:
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    declared_affected_count = int(
        totals.get(
            "affected_beneficiary_count",
            0,
        )
    )

    if declared_affected_count != len(
        affected_beneficiary_ids
    ):
        errors.append(
            "[semantic-error] "
            "totals.affected_beneficiary_count: "
            f"declared {declared_affected_count}, "
            f"calculated {len(affected_beneficiary_ids)}"
        )

    declared_open_count = int(
        totals.get("open_dispute_count", 0)
    )

    if declared_open_count != open_dispute_count:
        errors.append(
            "[semantic-error] totals.open_dispute_count: "
            f"declared {declared_open_count}, "
            f"calculated {open_dispute_count}"
        )

    declared_resolved_count = int(
        totals.get("resolved_dispute_count", 0)
    )

    if declared_resolved_count != resolved_dispute_count:
        errors.append(
            "[semantic-error] totals.resolved_dispute_count: "
            f"declared {declared_resolved_count}, "
            f"calculated {resolved_dispute_count}"
        )

    if effective_holdback_total != (
        released_total
        + current_held_total
        + returned_to_pool_total
    ):
        errors.append(
            "[semantic-error] totals: "
            "effective holdback must equal released + held + returned"
        )

    errors.extend(
        validate_approval_state(
            document,
            "ledger_status",
        )
    )

    errors.extend(
        validate_required_true_fields(
            document.get("review_control", {}),
            [
                "partial_processing_allowed",
                "unaffected_allocations_may_proceed",
                "automatic_dispute_resolution_prohibited",
            ],
            "review_control",
        )
    )

    errors.extend(
        validate_required_true_fields(
            document.get("safety_boundary", {}),
            [
                "evidence_required",
                "dispute_scope_required",
                "global_freeze_without_scope_prohibited",
                "automatic_dispute_resolution_prohibited",
                (
                    "held_amount_redistribution_without_"
                    "approval_prohibited"
                ),
                "autonomous_payment_prohibited",
                "human_approval_required",
            ],
            "safety_boundary",
        )
    )

    return errors


# Descriptive alias retained for compatibility.
validate_dispute_holdback_ledger = validate_v04


# ---------------------------------------------------------------------------
# Targets and execution
# ---------------------------------------------------------------------------


def targets() -> list[Target]:
    """Return all validation targets."""

    return [
        Target(
            "Allocation Ledger Record",
            ROOT
            / "schemas"
            / "allocation-ledger-record.schema.json",
            ROOT
            / "examples"
            / "pass"
            / "allocation-ledger-record.example.yaml",
            validate_v01,
        ),
        Target(
            "Contribution Weight Resolution",
            ROOT
            / "schemas"
            / "contribution-weight-resolution.schema.json",
            ROOT
            / "examples"
            / "pass"
            / "contribution-weight-resolution.example.yaml",
            validate_v02,
        ),
        Target(
            "Multi-Beneficiary Allocation Plan",
            ROOT
            / "schemas"
            / "multi-beneficiary-allocation-plan.schema.json",
            ROOT
            / "examples"
            / "pass"
            / "multi-beneficiary-allocation-plan.example.yaml",
            validate_v03,
        ),
        Target(
            "Dispute and Holdback Ledger",
            ROOT
            / "schemas"
            / "dispute-holdback-ledger.schema.json",
            ROOT
            / "examples"
            / "pass"
            / "dispute-holdback-ledger.example.yaml",
            validate_v04,
        ),
    ]


def validate_target(
    target: Target,
) -> list[str]:
    """Validate one schema/example pair."""

    if not target.schema.exists():
        return [
            f"[fatal] Schema not found: "
            f"{target.schema.relative_to(ROOT)}"
        ]

    if not target.example.exists():
        return [
            f"[fatal] Example not found: "
            f"{target.example.relative_to(ROOT)}"
        ]

    try:
        schema = load(target.schema)
    except Exception as error:
        return [
            f"[fatal] Failed to load schema "
            f"{target.schema.relative_to(ROOT)}: "
            f"{type(error).__name__}: {error}"
        ]

    try:
        document = load(target.example)
    except Exception as error:
        return [
            f"[fatal] Failed to load example "
            f"{target.example.relative_to(ROOT)}: "
            f"{type(error).__name__}: {error}"
        ]

    if not isinstance(schema, dict):
        return [
            f"[fatal] Schema root must be an object: "
            f"{target.schema.relative_to(ROOT)}"
        ]

    if not isinstance(document, dict):
        return [
            f"[fatal] Example root must be an object: "
            f"{target.example.relative_to(ROOT)}"
        ]

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        return [
            f"[fatal] Invalid JSON Schema "
            f"{target.schema.relative_to(ROOT)}: "
            f"{type(error).__name__}: {error}"
        ]

    errors = schema_errors(
        document,
        schema,
    )

    if not errors:
        errors.extend(
            target.validate(document)
        )

    return errors


def main() -> int:
    """Validate all repository examples."""

    print(
        "=== Royalty Allocation Ledger "
        "Agent Validation ==="
    )
    print()

    failed = False

    for target in targets():
        print(f"[validate] {target.name}")
        print(
            f"  schema : "
            f"{target.schema.relative_to(ROOT)}"
        )
        print(
            f"  example: "
            f"{target.example.relative_to(ROOT)}"
        )

        try:
            errors = validate_target(target)
        except Exception as error:
            errors = [
                f"[fatal] "
                f"{type(error).__name__}: {error}"
            ]

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

    print(
        "All Royalty Allocation Ledger "
        "Agent examples are valid."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
