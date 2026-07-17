#!/usr/bin/env python3
"""
Validate Royalty Allocation Ledger Agent examples.

Supported specifications:
- v0.1 Allocation Ledger Record
- v0.2 Contribution Weight Resolution
- v0.3 Multi-Beneficiary Allocation Plan
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


@dataclass(frozen=True)
class ValidationTarget:
    name: str
    schema_path: Path
    example_path: Path
    semantic_validator: Callable[[dict[str, Any]], list[str]]


def load_document(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() == ".json":
            return json.load(file)

        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(file)

    raise ValueError(f"Unsupported file type: {path}")


def decimal_value(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be a valid numeric value: {value!r}"
        ) from error


def approximately_equal(
    left: Decimal,
    right: Decimal,
    tolerance: Decimal = Decimal("0.000001"),
) -> bool:
    return abs(left - right) <= tolerance


def validate_schema(
    document: Any,
    schema: dict[str, Any],
) -> list[str]:
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


def declared_source_ids(
    document: dict[str, Any],
) -> set[str]:
    return {
        str(record.get("record_id"))
        for record in (
            document
            .get("source_context", {})
            .get("source_records", [])
        )
        if record.get("record_id")
    }


def validate_evidence_refs(
    evidence_refs: list[dict[str, Any]],
    source_ids: set[str],
    prefix: str,
) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    if not evidence_refs:
        return [
            f"[semantic-error] {prefix}: "
            "at least one evidence reference is required"
        ]

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

        if record_id not in source_ids:
            errors.append(
                f"[semantic-error] {evidence_prefix}.record_id: "
                f"'{record_id}' is not declared in source_context"
            )

    return errors


def validate_required_true_fields(
    record: dict[str, Any],
    field_names: list[str],
    prefix: str,
) -> list[str]:
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
    record_status_field: str,
) -> list[str]:
    errors: list[str] = []

    approval_status = document.get("approval", {}).get("status")
    record_status = document.get(record_status_field)

    if approval_status == "pending":
        if record_status not in {
            "draft",
            "pending_human_approval",
        }:
            errors.append(
                f"[semantic-error] {record_status_field}: "
                "pending approval requires draft or "
                "pending_human_approval"
            )

    elif approval_status == "approved":
        if record_status != "approved":
            errors.append(
                f"[semantic-error] {record_status_field}: "
                "approved human review requires approved status"
            )

    elif approval_status == "rejected":
        if record_status != "rejected":
            errors.append(
                f"[semantic-error] {record_status_field}: "
                "rejected human review requires rejected status"
            )

    return errors


# ---------------------------------------------------------------------------
# v0.1
# ---------------------------------------------------------------------------


def validate_allocation_ledger(
    document: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    gross_sum = Decimal("0")
    payable_sum = Decimal("0")
    held_sum = Decimal("0")

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

        gross_sum += gross
        payable_sum += payable
        held_sum += held

        if gross != payable + held:
            errors.append(
                f"[semantic-error] {prefix}: "
                "gross_allocation must equal payable_amount + held_amount"
            )

        errors.extend(
            validate_evidence_refs(
                beneficiary.get("evidence_refs", []),
                source_ids,
                f"{prefix}.evidence_refs",
            )
        )

        status = beneficiary.get("allocation_status")
        hold_reasons = beneficiary.get("hold_reasons", [])

        if held > 0 and not hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "positive held amount requires a hold reason"
            )

        if held == 0 and hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "hold reasons are not allowed when held amount is zero"
            )

        expected_status: str | None = None

        if payable > 0 and held == 0:
            expected_status = "payable"
        elif payable > 0 and held > 0:
            expected_status = "partially_held"
        elif payable == 0 and held > 0:
            expected_status = "fully_held"

        if expected_status and status != expected_status:
            errors.append(
                f"[semantic-error] {prefix}.allocation_status: "
                f"expected '{expected_status}'"
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
    rounding = decimal_value(
        totals.get("rounding_adjustment", 0),
        "totals.rounding_adjustment",
    )
    distributable = decimal_value(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
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
            "[semantic-error] totals: gross must equal payable + held"
        )

    if distributable != declared_gross + unallocated + rounding:
        errors.append(
            "[semantic-error] royalty_pool.distributable_amount: "
            "must equal gross allocation + unallocated + rounding"
        )

    errors.extend(
        validate_approval_state(document, "ledger_status")
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
# v0.2
# ---------------------------------------------------------------------------


def validate_weight_resolution(
    document: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    method = document.get("resolution_method", {})
    precision = int(method.get("precision", 6))
    tolerance = Decimal("1").scaleb(-precision)
    held_treatment = method.get("held_weight_treatment")

    component_total = Decimal("0")
    adjustment_total = Decimal("0")
    adjusted_total = Decimal("0")
    weight_total = Decimal("0")

    eligible_total = Decimal("0")
    records: list[tuple[int, str, Decimal, Decimal]] = []

    included_count = 0
    held_count = 0
    excluded_count = 0

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

        beneficiary_component_sum = Decimal("0")

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

            expected = raw_score * multiplier

            if not approximately_equal(
                weighted_score,
                expected,
                tolerance,
            ):
                errors.append(
                    f"[semantic-error] "
                    f"{component_prefix}.weighted_score: "
                    f"expected {expected}, found {weighted_score}"
                )

            beneficiary_component_sum += weighted_score

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
            beneficiary_component_sum,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.component_total: "
                f"declared {declared_component_total}, "
                f"calculated {beneficiary_component_sum}"
            )

        beneficiary_adjustment_sum = sum(
            (
                decimal_value(
                    item.get("delta_score", 0),
                    f"{prefix}.adjustments.delta_score",
                )
                for item in beneficiary.get("adjustments", [])
            ),
            Decimal("0"),
        )

        adjusted_score = decimal_value(
            beneficiary.get("adjusted_score", 0),
            f"{prefix}.adjusted_score",
        )

        expected_adjusted = (
            declared_component_total
            + beneficiary_adjustment_sum
        )

        if not approximately_equal(
            adjusted_score,
            expected_adjusted,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.adjusted_score: "
                f"expected {expected_adjusted}, found {adjusted_score}"
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

        if status == "included":
            included_count += 1
            eligible_total += adjusted_score

        elif status == "held_for_review":
            held_count += 1

            if not beneficiary.get("hold_reasons"):
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: "
                    "held beneficiary requires a reason"
                )

            if held_treatment == "reserve_in_normalization":
                eligible_total += adjusted_score

        elif status == "excluded":
            excluded_count += 1

            if adjusted_score != 0 or normalized_weight != 0:
                errors.append(
                    f"[semantic-error] {prefix}: "
                    "excluded beneficiary must have zero score and weight"
                )

        component_total += declared_component_total
        adjustment_total += beneficiary_adjustment_sum
        adjusted_total += adjusted_score
        weight_total += normalized_weight

        records.append(
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
        for index, status, adjusted_score, weight in records:
            eligible = (
                status == "included"
                or (
                    status == "held_for_review"
                    and held_treatment == "reserve_in_normalization"
                )
            )

            if eligible:
                expected_weight = adjusted_score / eligible_total

                if not approximately_equal(
                    weight,
                    expected_weight,
                    tolerance,
                ):
                    errors.append(
                        f"[semantic-error] "
                        f"beneficiaries[{index}].normalized_weight: "
                        f"expected {expected_weight}, found {weight}"
                    )

    totals = document.get("totals", {})

    checks = [
        (
            "component_total",
            decimal_value(
                totals.get("component_total", 0),
                "totals.component_total",
            ),
            component_total,
        ),
        (
            "adjustment_total",
            decimal_value(
                totals.get("adjustment_total", 0),
                "totals.adjustment_total",
            ),
            adjustment_total,
        ),
        (
            "adjusted_score_total",
            decimal_value(
                totals.get("adjusted_score_total", 0),
                "totals.adjusted_score_total",
            ),
            adjusted_total,
        ),
        (
            "normalized_weight_total",
            decimal_value(
                totals.get("normalized_weight_total", 0),
                "totals.normalized_weight_total",
            ),
            weight_total,
        ),
    ]

    for field_name, declared, calculated in checks:
        if not approximately_equal(
            declared,
            calculated,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    count_checks = [
        (
            "included_count",
            included_count,
        ),
        (
            "held_count",
            held_count,
        ),
        (
            "excluded_count",
            excluded_count,
        ),
    ]

    for field_name, calculated in count_checks:
        declared = int(totals.get(field_name, 0))

        if declared != calculated:
            errors.append(
                f"[semantic-error] totals.{field_name}: "
                f"declared {declared}, calculated {calculated}"
            )

    errors.extend(
        validate_approval_state(document, "resolution_status")
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
# v0.3
# ---------------------------------------------------------------------------


def rounding_mode(method: str) -> str:
    modes = {
        "half_up": ROUND_HALF_UP,
        "half_even": ROUND_HALF_EVEN,
        "floor": ROUND_FLOOR,
        "ceiling": ROUND_CEILING,
    }

    if method not in modes:
        raise ValueError(f"Unsupported rounding method: {method}")

    return modes[method]


def rounded_value(
    value: Decimal,
    decimal_places: int,
    method: str,
) -> Decimal:
    quantum = Decimal("1").scaleb(-decimal_places)

    return value.quantize(
        quantum,
        rounding=rounding_mode(method),
    )


def validate_multi_beneficiary_plan(
    document: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    source_ids = declared_source_ids(document)
    beneficiary_ids: set[str] = set()

    source_context = document.get("source_context", {})
    weight_resolution_id = str(
        source_context.get("weight_resolution_id")
    )

    policy = document.get("policy_application", {})
    rounding_policy = policy.get("rounding_policy", {})

    rounding_method = str(
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
        beneficiary_id = str(beneficiary.get("beneficiary_id"))

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: "
                f"duplicate beneficiary '{beneficiary_id}'"
            )

        beneficiary_ids.add(beneficiary_id)

        mode = str(beneficiary.get("allocation_mode"))
        state = str(beneficiary.get("plan_state"))
        calculation = beneficiary.get("calculation", {})

        basis_amount = decimal_value(
            calculation.get("basis_amount", 0),
            f"{prefix}.calculation.basis_amount",
        )
        raw_amount = decimal_value(
            calculation.get("raw_amount", 0),
            f"{prefix}.calculation.raw_amount",
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
        constraint_adjustment = decimal_value(
            calculation.get("constraint_adjustment", 0),
            f"{prefix}.calculation.constraint_adjustment",
        )

        expected_raw: Decimal | None = None

        if mode == "fixed_amount":
            fixed_amount = decimal_value(
                calculation.get("fixed_amount", 0),
                f"{prefix}.calculation.fixed_amount",
            )
            expected_raw = fixed_amount

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
                source_weight.get("resolution_id")
            )
            source_beneficiary_id = str(
                source_weight.get("beneficiary_id")
            )
            source_status = str(
                source_weight.get("resolution_status")
            )
            source_normalized_weight = decimal_value(
                source_weight.get("normalized_weight", 0),
                f"{prefix}.source_weight_ref.normalized_weight",
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
                    "must match the approved source weight"
                )

            if (
                source_status == "held_for_review"
                and state != "reserved_for_review"
            ):
                errors.append(
                    f"[semantic-error] {prefix}.plan_state: "
                    "held source weight must remain reserved"
                )

            expected_raw = basis_amount * normalized_weight
            proportional_weight_total += normalized_weight

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
                f"[semantic-error] {prefix}.calculation.raw_amount: "
                f"expected {expected_raw}, found {raw_amount}"
            )

        constrained_amount = raw_amount + constraint_adjustment

        minimum_amount = calculation.get("minimum_amount")
        maximum_amount = calculation.get("maximum_amount")

        if minimum_amount is not None:
            minimum = decimal_value(
                minimum_amount,
                f"{prefix}.calculation.minimum_amount",
            )

            if constrained_amount < minimum:
                errors.append(
                    f"[semantic-error] {prefix}.calculation: "
                    "amount remains below the declared minimum"
                )

        if maximum_amount is not None:
            maximum = decimal_value(
                maximum_amount,
                f"{prefix}.calculation.maximum_amount",
            )

            if constrained_amount > maximum:
                errors.append(
                    f"[semantic-error] {prefix}.calculation: "
                    "amount exceeds the declared maximum"
                )

        expected_rounded = rounded_value(
            constrained_amount,
            decimal_places,
            rounding_method,
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
            declared_rounded + remainder_adjustment
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

    for field_name, declared, calculated in calculated_checks:
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
            "must equal the proportional pool after remainder handling"
        )

    if not approximately_equal(
        declared_final,
        declared_fixed + declared_proportional,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.final_plan_total: "
            "must equal fixed allocation + proportional allocation"
        )

    if not approximately_equal(
        declared_final,
        declared_payable + declared_reserved,
        tolerance,
    ):
        errors.append(
            "[semantic-error] totals.final_plan_total: "
            "must equal payable candidates + reserved allocations"
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
            "pool must equal final plan + unallocated + residual"
        )

    errors.extend(
        validate_approval_state(document, "plan_status")
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


def validate_target(
    target: ValidationTarget,
) -> list[str]:
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

    errors = validate_schema(document, schema)

    if not errors:
        errors.extend(
            target.semantic_validator(document)
        )

    return errors


def main() -> int:
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
            semantic_validator=validate_weight_resolution,
        ),
        ValidationTarget(
            name="Multi-Beneficiary Allocation Plan",
            schema_path=(
                ROOT
                / "schemas"
                / "multi-beneficiary-allocation-plan.schema.json"
            ),
            example_path=(
                ROOT
                / "examples"
                / "pass"
                / "multi-beneficiary-allocation-plan.example.yaml"
            ),
            semantic_validator=validate_multi_beneficiary_plan,
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

    print(
        "All Royalty Allocation Ledger Agent "
        "examples are valid."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## `README.md`への追記

````markdown
## v0.3 — Multi-Beneficiary Allocation Plan

v0.3 converts approved contribution weights and policy-defined fixed
allocations into provisional monetary amounts.

The allocation sequence is:

```text
Approved Weight Resolution
        ↓
Fixed Funds and Fees
        ↓
Remaining Proportional Pool
        ↓
Normalized Weights
        ↓
Minimum and Maximum Constraints
        ↓
Rounding and Remainder Handling
        ↓
Multi-Beneficiary Allocation Plan
        ↓
Human Approval
````

v0.3 supports:

* fixed amounts
* fixed rates
* proportional weights
* pooled weights
* community funds
* platform fees
* minimum amounts
* maximum amounts
* rounding rules
* remainder handling
* reserved allocations
* unallocated balances

### Held Weight Boundary

A weight marked `held_for_review` must remain reserved when translated into
an allocation amount.

It must not be removed and redistributed to other beneficiaries.

### Allocation Boundary

An approved allocation plan is not a settlement instruction.

```text
Approved Allocation Plan
        ≠
Executed Payment
```

Identity checks, tax boundaries, payment endpoints, dispute release, and
settlement execution are outside the scope of v0.3.

### Core Principle

> Approved weights may be translated into amounts, but unresolved shares must
> remain reserved and no payment may be executed from the allocation plan.

````

Status欄：

```markdown
## Status

Current specification:

```text
v0.3.0-candidate
````

Implemented layers:

```text
v0.1  Allocation Ledger Record
v0.2  Contribution Weight Resolution
v0.3  Multi-Beneficiary Allocation Plan
```

Planned layers:

```text
v0.4  Dispute and Holdback Ledger
v0.5  Settlement Handoff and Royalty Audit
```

````

## `CHANGELOG.md`への追記

```markdown
## [0.3.0-candidate] - 2026-07-18

### Added

- Multi-Beneficiary Allocation Plan specification.
- Conversion of approved contribution weights into provisional amounts.
- Fixed-amount allocations.
- Fixed-rate allocations.
- Proportional-weight allocations.
- Pooled-weight allocations.
- Community fund allocations.
- Platform fee allocations.
- Allocation ordering rules.
- Proportional pool calculation.
- Minimum and maximum amount constraints.
- Constraint adjustment records.
- Currency rounding policy.
- Remainder handling policy.
- Payable candidate state.
- Reserved-for-review state.
- Excluded allocation state.
- Explicit preservation of held weights.
- Allocation-plan totals for:
  - fixed allocations
  - proportional allocations
  - payable candidates
  - reserved amounts
  - unallocated amounts
  - rounding residuals
- Default multi-beneficiary allocation policy example.
- Semantic validation for:
  - duplicate beneficiaries
  - approved weight references
  - weight-resolution identity
  - fixed-rate calculations
  - fixed-amount calculations
  - proportional calculations
  - approved weight preservation
  - minimum and maximum constraints
  - currency rounding
  - remainder adjustments
  - reserved-weight preservation
  - fixed and proportional totals
  - pool conservation
  - approval-state consistency
  - mandatory safety boundaries

### Changed

- Expanded the validation script to cover v0.1, v0.2, and v0.3.
- Added currency-aware rounding validation.
- Added explicit fixed-allocation and proportional-pool separation.
- Added a prohibition against redistributing held weights.

### Scope

v0.3 creates provisional multi-beneficiary allocation amounts.

It does not:

- create attribution
- change approved weights
- resolve disputes
- release reserved amounts
- determine tax obligations
- validate payment endpoints
- generate executable settlement instructions
- execute payments

### Core Boundary

> Approved weights may be translated into amounts, but unresolved shares must
> remain reserved and no payment may be executed from the allocation plan.
````
