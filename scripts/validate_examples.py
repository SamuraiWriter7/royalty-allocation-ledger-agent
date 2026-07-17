#!/usr/bin/env python3
"""Validate v0.1-v0.3 examples for royalty-allocation-ledger-agent."""

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
SemanticValidator = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class Target:
    name: str
    schema: Path
    example: Path
    validate: SemanticValidator


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() == ".json":
            return json.load(file)
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(file)
    raise ValueError(f"Unsupported file type: {path}")


def number(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric: {value!r}") from error


def near(a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
    return abs(a - b) <= tolerance


def schema_errors(document: Any, schema: dict[str, Any]) -> list[str]:
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
        errors.append(
            f"[schema-error] {path or '<root>'}: {error.message}"
        )

    return errors


def source_ids(document: dict[str, Any]) -> set[str]:
    records = document.get("source_context", {}).get("source_records", [])
    return {
        str(record.get("record_id"))
        for record in records
        if record.get("record_id")
    }


def validate_evidence(
    refs: list[dict[str, Any]],
    declared_ids: set[str],
    prefix: str,
) -> list[str]:
    if not refs:
        return [f"[semantic-error] {prefix}: evidence is required"]

    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for index, ref in enumerate(refs):
        item = f"{prefix}[{index}]"
        key = (
            str(ref.get("record_type")),
            str(ref.get("record_id")),
            str(ref.get("relation")),
        )

        if key in seen:
            errors.append(f"[semantic-error] {item}: duplicate evidence")
        seen.add(key)

        if ref.get("verified") is not True:
            errors.append(f"[semantic-error] {item}.verified: must be true")

        if str(ref.get("record_id")) not in declared_ids:
            errors.append(
                f"[semantic-error] {item}.record_id: "
                "not declared in source_context"
            )

    return errors


def validate_unique_sources(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    records = document.get("source_context", {}).get("source_records", [])

    for index, record in enumerate(records):
        record_id = str(record.get("record_id"))
        if record_id in seen:
            errors.append(
                "[semantic-error] "
                f"source_context.source_records[{index}].record_id: "
                f"duplicate source '{record_id}'"
            )
        seen.add(record_id)

    return errors


def validate_approval(
    document: dict[str, Any],
    status_field: str,
) -> list[str]:
    approval = document.get("approval", {}).get("status")
    status = document.get(status_field)

    if approval == "pending" and status not in {
        "draft",
        "pending_human_approval",
    }:
        return [
            f"[semantic-error] {status_field}: pending approval mismatch"
        ]
    if approval == "approved" and status != "approved":
        return [
            f"[semantic-error] {status_field}: approved status mismatch"
        ]
    if approval == "rejected" and status != "rejected":
        return [
            f"[semantic-error] {status_field}: rejected status mismatch"
        ]
    return []


def validate_boundary(
    document: dict[str, Any],
    fields: list[str],
) -> list[str]:
    boundary = document.get("safety_boundary", {})
    return [
        f"[semantic-error] safety_boundary.{field}: must remain true"
        for field in fields
        if boundary.get(field) is not True
    ]


# v0.1 ---------------------------------------------------------------------


def validate_v01(document: dict[str, Any]) -> list[str]:
    errors = validate_unique_sources(document)
    declared_ids = source_ids(document)
    beneficiary_ids: set[str] = set()
    gross_sum = Decimal("0")
    payable_sum = Decimal("0")
    held_sum = Decimal("0")

    for index, beneficiary in enumerate(document.get("beneficiaries", [])):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(beneficiary.get("beneficiary_id"))

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: duplicate"
            )
        beneficiary_ids.add(beneficiary_id)

        gross = number(
            beneficiary.get("gross_allocation", 0),
            f"{prefix}.gross_allocation",
        )
        payable = number(
            beneficiary.get("payable_amount", 0),
            f"{prefix}.payable_amount",
        )
        held = number(
            beneficiary.get("held_amount", 0),
            f"{prefix}.held_amount",
        )
        gross_sum += gross
        payable_sum += payable
        held_sum += held

        if gross != payable + held:
            errors.append(
                f"[semantic-error] {prefix}: gross must equal payable + held"
            )

        errors.extend(
            validate_evidence(
                beneficiary.get("evidence_refs", []),
                declared_ids,
                f"{prefix}.evidence_refs",
            )
        )

        status = beneficiary.get("allocation_status")
        reasons = beneficiary.get("hold_reasons", [])

        if held > 0 and not reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: required"
            )
        if held == 0 and reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: unexpected"
            )

        if gross == 0:
            expected = "rejected"
        elif payable > 0 and held == 0:
            expected = "payable"
        elif payable > 0 and held > 0:
            expected = "partially_held"
        else:
            expected = "fully_held"

        if status != expected:
            errors.append(
                f"[semantic-error] {prefix}.allocation_status: "
                f"expected '{expected}'"
            )

    totals = document.get("totals", {})
    pool = document.get("royalty_pool", {})
    declared_gross = number(
        totals.get("gross_allocated", 0),
        "totals.gross_allocated",
    )
    declared_payable = number(
        totals.get("payable_total", 0),
        "totals.payable_total",
    )
    declared_held = number(
        totals.get("held_total", 0),
        "totals.held_total",
    )
    unallocated = number(
        totals.get("unallocated_total", 0),
        "totals.unallocated_total",
    )
    rounding = number(
        totals.get("rounding_adjustment", 0),
        "totals.rounding_adjustment",
    )
    gross_pool = number(
        pool.get("gross_amount", 0),
        "royalty_pool.gross_amount",
    )
    distributable = number(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )
    excluded = number(
        pool.get("excluded_amount", 0),
        "royalty_pool.excluded_amount",
    )

    checks = [
        ("gross_allocated", declared_gross, gross_sum),
        ("payable_total", declared_payable, payable_sum),
        ("held_total", declared_held, held_sum),
    ]
    for field, declared, calculated in checks:
        if declared != calculated:
            errors.append(
                f"[semantic-error] totals.{field}: "
                f"declared {declared}, calculated {calculated}"
            )

    if declared_gross != declared_payable + declared_held:
        errors.append("[semantic-error] totals: gross/payable/held mismatch")
    if distributable != declared_gross + unallocated + rounding:
        errors.append("[semantic-error] royalty pool conservation failed")
    if gross_pool != distributable + excluded:
        errors.append("[semantic-error] gross pool conservation failed")

    errors.extend(validate_approval(document, "ledger_status"))
    errors.extend(
        validate_boundary(
            document,
            [
                "evidence_required",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "human_approval_required",
            ],
        )
    )
    return errors


# v0.2 ---------------------------------------------------------------------


def validate_v02(document: dict[str, Any]) -> list[str]:
    errors = validate_unique_sources(document)
    declared_ids = source_ids(document)
    method = document.get("resolution_method", {})
    precision = int(method.get("precision", 6))
    tolerance = Decimal("1").scaleb(-precision)
    target = number(
        method.get("normalization_target", 1),
        "resolution_method.normalization_target",
    )
    held_treatment = method.get("held_weight_treatment")

    beneficiary_ids: set[str] = set()
    component_total = Decimal("0")
    adjustment_total = Decimal("0")
    adjusted_total = Decimal("0")
    weight_total = Decimal("0")
    eligible_total = Decimal("0")
    counts = {"included": 0, "held_for_review": 0, "excluded": 0}
    rows: list[tuple[int, str, Decimal, Decimal]] = []

    for index, beneficiary in enumerate(document.get("beneficiaries", [])):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(beneficiary.get("beneficiary_id"))
        status = str(beneficiary.get("resolution_status"))

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: duplicate"
            )
        beneficiary_ids.add(beneficiary_id)

        for ref_index, record_id in enumerate(
            beneficiary.get("attribution_refs", [])
        ):
            if str(record_id) not in declared_ids:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.attribution_refs[{ref_index}]: undeclared"
                )

        component_sum = Decimal("0")
        for component_index, component in enumerate(
            beneficiary.get("components", [])
        ):
            item = f"{prefix}.components[{component_index}]"
            raw = number(component.get("raw_score", 0), f"{item}.raw_score")
            multiplier = number(
                component.get("policy_multiplier", 0),
                f"{item}.policy_multiplier",
            )
            weighted = number(
                component.get("weighted_score", 0),
                f"{item}.weighted_score",
            )
            if not near(weighted, raw * multiplier, tolerance):
                errors.append(
                    f"[semantic-error] {item}.weighted_score: invalid"
                )
            component_sum += weighted
            errors.extend(
                validate_evidence(
                    component.get("evidence_refs", []),
                    declared_ids,
                    f"{item}.evidence_refs",
                )
            )

        declared_component = number(
            beneficiary.get("component_total", 0),
            f"{prefix}.component_total",
        )
        if not near(declared_component, component_sum, tolerance):
            errors.append(
                f"[semantic-error] {prefix}.component_total: invalid"
            )

        adjustment_sum = Decimal("0")
        for adjustment_index, adjustment in enumerate(
            beneficiary.get("adjustments", [])
        ):
            item = f"{prefix}.adjustments[{adjustment_index}]"
            adjustment_sum += number(
                adjustment.get("delta_score", 0),
                f"{item}.delta_score",
            )
            if str(adjustment.get("policy_ref")) not in declared_ids:
                errors.append(
                    f"[semantic-error] {item}.policy_ref: undeclared"
                )
            errors.extend(
                validate_evidence(
                    adjustment.get("evidence_refs", []),
                    declared_ids,
                    f"{item}.evidence_refs",
                )
            )

        adjusted = number(
            beneficiary.get("adjusted_score", 0),
            f"{prefix}.adjusted_score",
        )
        if not near(
            adjusted,
            declared_component + adjustment_sum,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.adjusted_score: invalid"
            )

        weight = number(
            beneficiary.get("normalized_weight", 0),
            f"{prefix}.normalized_weight",
        )
        errors.extend(
            validate_evidence(
                beneficiary.get("evidence_refs", []),
                declared_ids,
                f"{prefix}.evidence_refs",
            )
        )

        hold_reasons = beneficiary.get("hold_reasons", [])
        exclusion_reasons = beneficiary.get("exclusion_reasons", [])
        counts[status] = counts.get(status, 0) + 1

        if status == "included":
            eligible_total += adjusted
            if hold_reasons or exclusion_reasons:
                errors.append(f"[semantic-error] {prefix}: invalid reasons")
        elif status == "held_for_review":
            if not hold_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.hold_reasons: required"
                )
            if exclusion_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.exclusion_reasons: unexpected"
                )
            if held_treatment == "reserve_in_normalization":
                eligible_total += adjusted
        elif status == "excluded":
            if not exclusion_reasons:
                errors.append(
                    f"[semantic-error] {prefix}.exclusion_reasons: required"
                )
            if adjusted != 0 or weight != 0:
                errors.append(
                    f"[semantic-error] {prefix}: excluded score must be zero"
                )

        component_total += declared_component
        adjustment_total += adjustment_sum
        adjusted_total += adjusted
        weight_total += weight
        rows.append((index, status, adjusted, weight))

    if eligible_total <= 0:
        errors.append("[semantic-error] eligible score must be positive")
    else:
        for index, status, adjusted, weight in rows:
            eligible = status == "included" or (
                status == "held_for_review"
                and held_treatment == "reserve_in_normalization"
            )
            if eligible and not near(
                weight,
                adjusted / eligible_total,
                tolerance,
            ):
                errors.append(
                    f"[semantic-error] "
                    f"beneficiaries[{index}].normalized_weight: invalid"
                )
            if (
                status == "held_for_review"
                and not eligible
                and weight != 0
            ):
                errors.append(
                    f"[semantic-error] "
                    f"beneficiaries[{index}].normalized_weight: must be zero"
                )

    totals = document.get("totals", {})
    checks = [
        (
            "component_total",
            number(totals.get("component_total", 0), "totals.component_total"),
            component_total,
        ),
        (
            "adjustment_total",
            number(totals.get("adjustment_total", 0), "totals.adjustment_total"),
            adjustment_total,
        ),
        (
            "adjusted_score_total",
            number(
                totals.get("adjusted_score_total", 0),
                "totals.adjusted_score_total",
            ),
            adjusted_total,
        ),
        (
            "normalized_weight_total",
            number(
                totals.get("normalized_weight_total", 0),
                "totals.normalized_weight_total",
            ),
            weight_total,
        ),
    ]
    for field, declared, calculated in checks:
        if not near(declared, calculated, tolerance):
            errors.append(
                f"[semantic-error] totals.{field}: "
                f"declared {declared}, calculated {calculated}"
            )

    declared_weight = checks[-1][1]
    residual = number(
        totals.get("normalization_residual", 0),
        "totals.normalization_residual",
    )
    if not near(residual, target - declared_weight, tolerance):
        errors.append("[semantic-error] normalization_residual: invalid")
    if not near(declared_weight, target, tolerance):
        errors.append("[semantic-error] normalized weights must total 1")

    for status, field in [
        ("included", "included_count"),
        ("held_for_review", "held_count"),
        ("excluded", "excluded_count"),
    ]:
        if int(totals.get(field, 0)) != counts.get(status, 0):
            errors.append(f"[semantic-error] totals.{field}: invalid")

    errors.extend(validate_approval(document, "resolution_status"))
    errors.extend(
        validate_boundary(
            document,
            [
                "verified_attribution_required",
                "attribution_rewrite_prohibited",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "human_approval_required",
            ],
        )
    )
    return errors


# v0.3 ---------------------------------------------------------------------


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


def round_value(value: Decimal, places: int, method: str) -> Decimal:
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=rounding_mode(method))


def validate_v03(document: dict[str, Any]) -> list[str]:
    errors = validate_unique_sources(document)
    declared_ids = source_ids(document)
    context = document.get("source_context", {})
    policy = document.get("policy_application", {})
    pool = document.get("royalty_pool", {})

    resolution_id = str(context.get("weight_resolution_id", ""))
    if str(policy.get("policy_id", "")) != str(
        context.get("allocation_policy_id", "")
    ):
        errors.append("[semantic-error] policy_id mismatch")
    if str(pool.get("pool_id", "")) != str(
        context.get("royalty_pool_record_id", "")
    ):
        errors.append("[semantic-error] pool_id mismatch")

    rounding = policy.get("rounding_policy", {})
    method = str(rounding.get("method", "half_up"))
    places = int(rounding.get("decimal_places", 0))
    tolerance = Decimal("1").scaleb(-(places + 4))

    distributable = number(
        pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )
    fixed_policy = number(
        policy.get("fixed_allocation_total", 0),
        "policy_application.fixed_allocation_total",
    )
    proportional_pool = number(
        policy.get("proportional_pool_amount", 0),
        "policy_application.proportional_pool_amount",
    )
    if not near(distributable, fixed_policy + proportional_pool, tolerance):
        errors.append("[semantic-error] policy pool conservation failed")

    beneficiary_ids: set[str] = set()
    fixed_total = Decimal("0")
    proportional_total = Decimal("0")
    final_total = Decimal("0")
    payable_total = Decimal("0")
    reserved_total = Decimal("0")
    weight_total = Decimal("0")

    for index, beneficiary in enumerate(document.get("beneficiaries", [])):
        prefix = f"beneficiaries[{index}]"
        beneficiary_id = str(beneficiary.get("beneficiary_id"))
        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: duplicate"
            )
        beneficiary_ids.add(beneficiary_id)

        mode = str(beneficiary.get("allocation_mode"))
        state = str(beneficiary.get("plan_state"))
        calc = beneficiary.get("calculation", {})
        basis = number(
            calc.get("basis_amount", 0),
            f"{prefix}.calculation.basis_amount",
        )
        raw = number(
            calc.get("raw_amount", 0),
            f"{prefix}.calculation.raw_amount",
        )
        constraint = number(
            calc.get("constraint_adjustment", 0),
            f"{prefix}.calculation.constraint_adjustment",
        )
        rounded = number(
            calc.get("rounded_amount", 0),
            f"{prefix}.calculation.rounded_amount",
        )
        remainder = number(
            calc.get("remainder_adjustment", 0),
            f"{prefix}.calculation.remainder_adjustment",
        )
        final = number(
            calc.get("final_planned_amount", 0),
            f"{prefix}.calculation.final_planned_amount",
        )

        expected_raw: Decimal | None = None
        if mode == "fixed_amount":
            expected_raw = number(
                calc.get("fixed_amount", 0),
                f"{prefix}.calculation.fixed_amount",
            )
        elif mode == "fixed_rate":
            rate = number(
                calc.get("fixed_rate", 0),
                f"{prefix}.calculation.fixed_rate",
            )
            expected_raw = basis * rate
            if not near(basis, distributable, tolerance):
                errors.append(
                    f"[semantic-error] {prefix}.basis_amount: invalid"
                )
        elif mode in {"proportional_weight", "pooled_weight"}:
            weight = number(
                calc.get("normalized_weight", 0),
                f"{prefix}.calculation.normalized_weight",
            )
            source = beneficiary.get("source_weight_ref", {})
            source_weight = number(
                source.get("normalized_weight", 0),
                f"{prefix}.source_weight_ref.normalized_weight",
            )
            if str(source.get("resolution_id", "")) != resolution_id:
                errors.append(
                    f"[semantic-error] {prefix}.resolution_id: mismatch"
                )
            if str(source.get("beneficiary_id", "")) != beneficiary_id:
                errors.append(
                    f"[semantic-error] {prefix}.source beneficiary: mismatch"
                )
            if not near(weight, source_weight, tolerance):
                errors.append(
                    f"[semantic-error] {prefix}.normalized_weight: mismatch"
                )
            if not near(basis, proportional_pool, tolerance):
                errors.append(
                    f"[semantic-error] {prefix}.basis_amount: invalid"
                )
            if (
                source.get("resolution_status") == "held_for_review"
                and state != "reserved_for_review"
            ):
                errors.append(
                    f"[semantic-error] {prefix}.plan_state: "
                    "held weight must remain reserved"
                )
            expected_raw = basis * weight
            weight_total += weight
        elif mode == "remainder_assignment":
            expected_raw = raw

        if expected_raw is not None and not near(
            raw,
            expected_raw,
            tolerance,
        ):
            errors.append(
                f"[semantic-error] {prefix}.raw_amount: invalid"
            )

        constrained = raw + constraint
        expected_rounded = round_value(constrained, places, method)
        if not near(rounded, expected_rounded, tolerance):
            errors.append(
                f"[semantic-error] {prefix}.rounded_amount: invalid"
            )
        if not near(final, rounded + remainder, tolerance):
            errors.append(
                f"[semantic-error] {prefix}.final_planned_amount: invalid"
            )

        reasons = beneficiary.get("reserve_reasons", [])
        if state == "reserved_for_review":
            if not reasons:
                errors.append(
                    f"[semantic-error] {prefix}.reserve_reasons: required"
                )
            reserved_total += final
        elif state == "planned_payable":
            if reasons:
                errors.append(
                    f"[semantic-error] {prefix}.reserve_reasons: unexpected"
                )
            payable_total += final
        elif state == "excluded" and final != 0:
            errors.append(
                f"[semantic-error] {prefix}: excluded amount must be zero"
            )

        errors.extend(
            validate_evidence(
                beneficiary.get("evidence_refs", []),
                declared_ids,
                f"{prefix}.evidence_refs",
            )
        )

        if mode in {"fixed_amount", "fixed_rate", "remainder_assignment"}:
            fixed_total += final
        elif mode in {"proportional_weight", "pooled_weight"}:
            proportional_total += final

        final_total += final

    if not near(weight_total, Decimal("1"), tolerance):
        errors.append("[semantic-error] proportional weights must total 1")

    totals = document.get("totals", {})
    declared_fixed = number(
        totals.get("fixed_allocation_total", 0),
        "totals.fixed_allocation_total",
    )
    declared_pool = number(
        totals.get("proportional_pool_amount", 0),
        "totals.proportional_pool_amount",
    )
    declared_proportional = number(
        totals.get("proportional_allocation_total", 0),
        "totals.proportional_allocation_total",
    )
    declared_final = number(
        totals.get("final_plan_total", 0),
        "totals.final_plan_total",
    )
    declared_payable = number(
        totals.get("payable_candidate_total", 0),
        "totals.payable_candidate_total",
    )
    declared_reserved = number(
        totals.get("reserved_total", 0),
        "totals.reserved_total",
    )
    unallocated = number(
        totals.get("unallocated_total", 0),
        "totals.unallocated_total",
    )
    residual = number(
        totals.get("rounding_residual", 0),
        "totals.rounding_residual",
    )

    checks = [
        ("fixed_allocation_total", declared_fixed, fixed_total),
        ("proportional_allocation_total", declared_proportional, proportional_total),
        ("final_plan_total", declared_final, final_total),
        ("payable_candidate_total", declared_payable, payable_total),
        ("reserved_total", declared_reserved, reserved_total),
    ]
    for field, declared, calculated in checks:
        if not near(declared, calculated, tolerance):
            errors.append(
                f"[semantic-error] totals.{field}: "
                f"declared {declared}, calculated {calculated}"
            )

    if not near(declared_fixed, fixed_policy, tolerance):
        errors.append("[semantic-error] fixed allocation policy mismatch")
    if not near(declared_pool, proportional_pool, tolerance):
        errors.append("[semantic-error] proportional pool policy mismatch")
    if not near(
        declared_final,
        declared_payable + declared_reserved,
        tolerance,
    ):
        errors.append("[semantic-error] payable/reserved total mismatch")

    expected_residual = proportional_pool - declared_proportional
    if not near(residual, expected_residual, tolerance):
        errors.append("[semantic-error] rounding_residual: invalid")
    if not near(distributable, declared_final + unallocated, tolerance):
        errors.append("[semantic-error] final plan does not conserve pool")

    strategy = policy.get("remainder_policy", {}).get("strategy")
    if strategy != "retain_unallocated" and residual != 0:
        errors.append(
            "[semantic-error] rounding residual must be resolved by policy"
        )

    errors.extend(validate_approval(document, "plan_status"))
    errors.extend(
        validate_boundary(
            document,
            [
                "approved_weight_resolution_required",
                "evidence_required",
                "rights_creation_prohibited",
                "autonomous_payment_prohibited",
                "held_weight_redistribution_prohibited",
                "human_approval_required",
            ],
        )
    )
    return errors


# Runner -------------------------------------------------------------------


def targets() -> list[Target]:
    return [
        Target(
            "Allocation Ledger Record",
            ROOT / "schemas" / "allocation-ledger-record.schema.json",
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
    ]


def validate_target(target: Target) -> list[str]:
    if not target.schema.exists():
        return [f"[fatal] Schema not found: {target.schema}"]
    if not target.example.exists():
        return [f"[fatal] Example not found: {target.example}"]

    schema = load(target.schema)
    document = load(target.example)
    if not isinstance(schema, dict):
        return [f"[fatal] Schema root must be an object: {target.schema}"]
    if not isinstance(document, dict):
        return [f"[fatal] Example root must be an object: {target.example}"]

    Draft202012Validator.check_schema(schema)
    errors = schema_errors(document, schema)
    if not errors:
        errors.extend(target.validate(document))
    return errors


def main() -> int:
    print("=== Royalty Allocation Ledger Agent Validation ===")
    print()
    failed = False

    for target in targets():
        print(f"[validate] {target.name}")
        print(f"  schema : {target.schema.relative_to(ROOT)}")
        print(f"  example: {target.example.relative_to(ROOT)}")

        try:
            errors = validate_target(target)
        except Exception as error:
            errors = [f"[fatal] {type(error).__name__}: {error}"]

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
