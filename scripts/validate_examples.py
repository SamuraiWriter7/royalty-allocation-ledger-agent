#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]

SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "multi-beneficiary-allocation-plan.schema.json"
)

PASS_EXAMPLE = (
    ROOT
    / "examples"
    / "pass"
    / "multi-beneficiary-allocation-plan.example.yaml"
)

FAIL_EXAMPLE = (
    ROOT
    / "examples"
    / "fail"
    / "invalid-proportional-allocation.example.yaml"
)

EPSILON = 0.000001


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")

    return data


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")

    return data


def close_enough(left: float, right: float) -> bool:
    return math.isclose(
        left,
        right,
        abs_tol=EPSILON,
        rel_tol=0.0,
    )


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(
        {
            value
            for value in values
            if values.count(value) > 1
        }
    )


def schema_errors(
    validator: Draft202012Validator,
    record: dict[str, Any],
) -> list[str]:
    return [
        (
            f"{('.'.join(str(part) for part in error.absolute_path) or '<root>')}: "
            f"{error.message}"
        )
        for error in sorted(
            validator.iter_errors(record),
            key=lambda item: list(item.absolute_path),
        )
    ]


def semantic_errors(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    source = record["source_resolution"]
    pool = record["royalty_pool"]
    policy_allocations = record["policy_allocations"]
    proportional = record["proportional_distribution"]
    totals = record["beneficiary_totals"]
    reserve = record["reserve"]
    summary = record["integrity_summary"]
    review = record["human_review"]
    downstream = record["downstream_state"]

    gross = float(pool["gross_amount"])
    deductions = float(pool["deduction_amount"])
    allocatable = float(pool["allocatable_amount"])

    if not close_enough(gross - deductions, allocatable):
        errors.append(
            "royalty_pool.allocatable_amount must equal "
            "gross_amount minus deduction_amount"
        )

    if proportional["weight_source_resolution_id"] != source["resolution_id"]:
        errors.append(
            "proportional_distribution.weight_source_resolution_id "
            "must match source_resolution.resolution_id"
        )

    allocation_ids = [
        item["allocation_id"]
        for item in policy_allocations
    ]

    duplicate_allocation_ids = duplicate_values(
        allocation_ids
    )

    if duplicate_allocation_ids:
        errors.append(
            "duplicate policy allocation_id values: "
            + ", ".join(duplicate_allocation_ids)
        )

    priorities = [
        int(item["priority"])
        for item in policy_allocations
    ]

    duplicate_priorities = duplicate_values(
        [str(value) for value in priorities]
    )

    if duplicate_priorities:
        errors.append(
            "duplicate policy allocation priorities: "
            + ", ".join(duplicate_priorities)
        )

    current_remaining = allocatable
    policy_total = 0.0

    sorted_allocations = sorted(
        policy_allocations,
        key=lambda value: int(value["priority"]),
    )

    for index, item in enumerate(sorted_allocations):
        method = item["method"]
        base = float(item["calculation_base_amount"])
        calculated = float(item["calculated_amount"])

        if method == "fixed_amount":
            if "fixed_amount" not in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "fixed_amount method requires fixed_amount"
                )
                expected = calculated
            else:
                expected = float(item["fixed_amount"])

            if "rate" in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "fixed_amount method must not contain rate"
                )

        elif method == "percentage_of_allocatable_pool":
            if "rate" not in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "percentage method requires rate"
                )
                expected = calculated
            else:
                expected = allocatable * float(item["rate"])

            if "fixed_amount" in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "percentage method must not contain fixed_amount"
                )

            if not close_enough(base, allocatable):
                errors.append(
                    f"policy_allocations[{index}]: "
                    "calculation_base_amount must equal "
                    "allocatable pool"
                )

        elif method == "percentage_of_remaining_pool":
            if "rate" not in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "percentage method requires rate"
                )
                expected = calculated
            else:
                expected = (
                    current_remaining
                    * float(item["rate"])
                )

            if "fixed_amount" in item:
                errors.append(
                    f"policy_allocations[{index}]: "
                    "percentage method must not contain "
                    "fixed_amount"
                )

            if not close_enough(
                base,
                current_remaining,
            ):
                errors.append(
                    f"policy_allocations[{index}]: "
                    "calculation_base_amount must equal "
                    "the remaining pool at that priority stage"
                )

        else:
            expected = calculated

        if not close_enough(expected, calculated):
            errors.append(
                f"policy_allocations[{index}]: "
                "calculated_amount does not match "
                "the declared method and calculation base"
            )

        if calculated > current_remaining + EPSILON:
            errors.append(
                f"policy_allocations[{index}]: "
                "allocation exceeds the remaining pool"
            )

        current_remaining -= calculated
        policy_total += calculated

    policy_holdback = float(
        reserve["policy_holdback_amount"]
    )

    dispute_holdback = float(
        reserve["dispute_holdback_amount"]
    )

    rounding_remainder = float(
        reserve["rounding_remainder_amount"]
    )

    unallocated = float(
        reserve["unallocated_amount"]
    )

    expected_proportional_base = (
        allocatable
        - policy_total
        - policy_holdback
        - dispute_holdback
        - unallocated
    )

    proportional_base = float(
        proportional["base_amount"]
    )

    if not close_enough(
        expected_proportional_base,
        proportional_base,
    ):
        errors.append(
            "proportional_distribution.base_amount "
            "must equal the allocatable pool minus "
            "policy allocations, holdbacks, and "
            "explicit unallocated amount"
        )

    entries = proportional["entries"]

    entry_ids = [
        item["entry_id"]
        for item in entries
    ]

    duplicate_entry_ids = duplicate_values(
        entry_ids
    )

    if duplicate_entry_ids:
        errors.append(
            "duplicate proportional entry_id values: "
            + ", ".join(duplicate_entry_ids)
        )

    entry_beneficiaries = [
        item["beneficiary_id"]
        for item in entries
    ]

    duplicate_entry_beneficiaries = duplicate_values(
        entry_beneficiaries
    )

    if duplicate_entry_beneficiaries:
        errors.append(
            "duplicate proportional beneficiary_id values: "
            + ", ".join(duplicate_entry_beneficiaries)
        )

    source_weight_total = sum(
        float(item["source_normalized_weight"])
        for item in entries
    )

    effective_weight_total = sum(
        float(item["effective_weight"])
        for item in entries
    )

    signed_delta_total = 0.0
    distributed_total = 0.0

    for index, item in enumerate(entries):
        source_weight = float(
            item["source_normalized_weight"]
        )

        effective_weight = float(
            item["effective_weight"]
        )

        adjustment = item["weight_adjustment"]

        signed_delta = float(
            adjustment["signed_delta"]
        )

        applied = bool(
            adjustment["applied"]
        )

        base = float(
            item["calculation_base_amount"]
        )

        calculated = float(
            item["calculated_amount"]
        )

        if not close_enough(
            base,
            proportional_base,
        ):
            errors.append(
                f"proportional_distribution.entries[{index}]: "
                "calculation_base_amount must equal "
                "the proportional base"
            )

        if not close_enough(
            source_weight + signed_delta,
            effective_weight,
        ):
            errors.append(
                f"proportional_distribution.entries[{index}]: "
                "effective_weight must equal "
                "source_normalized_weight plus signed_delta"
            )

        if applied:
            if close_enough(signed_delta, 0.0):
                errors.append(
                    f"proportional_distribution.entries[{index}]: "
                    "an applied weight adjustment "
                    "requires a non-zero delta"
                )

            if not adjustment["rule_refs"]:
                errors.append(
                    f"proportional_distribution.entries[{index}]: "
                    "an applied weight adjustment "
                    "requires rule_refs"
                )

        else:
            if not close_enough(signed_delta, 0.0):
                errors.append(
                    f"proportional_distribution.entries[{index}]: "
                    "a non-applied adjustment requires "
                    "zero signed_delta"
                )

            if not close_enough(
                source_weight,
                effective_weight,
            ):
                errors.append(
                    f"proportional_distribution.entries[{index}]: "
                    "a non-applied adjustment cannot "
                    "change the weight"
                )

        expected_amount = (
            proportional_base
            * effective_weight
        )

        if not close_enough(
            expected_amount,
            calculated,
        ):
            errors.append(
                f"proportional_distribution.entries[{index}]: "
                "calculated_amount must equal "
                "proportional base multiplied by "
                "effective_weight"
            )

        signed_delta_total += signed_delta
        distributed_total += calculated

    if not close_enough(
        source_weight_total,
        1.0,
    ):
        errors.append(
            "source_normalized_weight values "
            "must sum to 1.0"
        )

    if not close_enough(
        effective_weight_total,
        1.0,
    ):
        errors.append(
            "effective_weight values must sum to 1.0"
        )

    if not close_enough(
        signed_delta_total,
        0.0,
    ):
        errors.append(
            "weight adjustment signed_delta values "
            "must sum to zero"
        )

    declared_distributed = float(
        proportional["distributed_amount"]
    )

    if not close_enough(
        distributed_total,
        declared_distributed,
    ):
        errors.append(
            "proportional_distribution."
            "distributed_amount does not match "
            "the sum of proportional entries"
        )

    if not close_enough(
        distributed_total + rounding_remainder,
        proportional_base,
    ):
        errors.append(
            "proportional entry amounts plus "
            "rounding remainder must equal "
            "the proportional base"
        )

    policy_by_id = {
        item["allocation_id"]: item
        for item in policy_allocations
    }

    entry_by_id = {
        item["entry_id"]: item
        for item in entries
    }

    total_beneficiary_ids = [
        item["beneficiary_id"]
        for item in totals
    ]

    duplicate_total_beneficiaries = duplicate_values(
        total_beneficiary_ids
    )

    if duplicate_total_beneficiaries:
        errors.append(
            "duplicate beneficiary_totals "
            "beneficiary_id values: "
            + ", ".join(duplicate_total_beneficiaries)
        )

    referenced_components: list[str] = []
    beneficiary_total_sum = 0.0

    for index, item in enumerate(totals):
        beneficiary_id = item["beneficiary_id"]

        declared_policy = float(
            item["policy_allocation_amount"]
        )

        declared_proportional = float(
            item["proportional_allocation_amount"]
        )

        declared_total = float(
            item["total_planned_amount"]
        )

        calculated_policy = 0.0
        calculated_proportional = 0.0

        for component_ref in item["component_refs"]:
            if component_ref in policy_by_id:
                component = policy_by_id[
                    component_ref
                ]

                if (
                    component["recipient_id"]
                    != beneficiary_id
                ):
                    errors.append(
                        f"beneficiary_totals[{index}]: "
                        f"policy component {component_ref} "
                        "belongs to another recipient"
                    )

                calculated_policy += float(
                    component["calculated_amount"]
                )

                referenced_components.append(
                    component_ref
                )

            elif component_ref in entry_by_id:
                component = entry_by_id[
                    component_ref
                ]

                if (
                    component["beneficiary_id"]
                    != beneficiary_id
                ):
                    errors.append(
                        f"beneficiary_totals[{index}]: "
                        "proportional component "
                        f"{component_ref} belongs to "
                        "another beneficiary"
                    )

                calculated_proportional += float(
                    component["calculated_amount"]
                )

                referenced_components.append(
                    component_ref
                )

            else:
                errors.append(
                    f"beneficiary_totals[{index}]: "
                    f"unknown component_ref {component_ref}"
                )

        if not close_enough(
            calculated_policy,
            declared_policy,
        ):
            errors.append(
                f"beneficiary_totals[{index}]: "
                "policy_allocation_amount does not "
                "match referenced policy components"
            )

        if not close_enough(
            calculated_proportional,
            declared_proportional,
        ):
            errors.append(
                f"beneficiary_totals[{index}]: "
                "proportional_allocation_amount does "
                "not match referenced proportional "
                "components"
            )

        if not close_enough(
            declared_policy
            + declared_proportional,
            declared_total,
        ):
            errors.append(
                f"beneficiary_totals[{index}]: "
                "total_planned_amount must equal "
                "policy plus proportional allocation "
                "amounts"
            )

        beneficiary_total_sum += declared_total

    duplicate_component_usage = duplicate_values(
        referenced_components
    )

    if duplicate_component_usage:
        errors.append(
            "allocation components referenced by "
            "multiple beneficiary totals: "
            + ", ".join(duplicate_component_usage)
        )

    all_component_ids = (
        set(allocation_ids)
        | set(entry_ids)
    )

    missing_components = sorted(
        all_component_ids
        - set(referenced_components)
    )

    if missing_components:
        errors.append(
            "allocation components missing from "
            "beneficiary_totals: "
            + ", ".join(missing_components)
        )

    unknown_components = sorted(
        set(referenced_components)
        - all_component_ids
    )

    if unknown_components:
        errors.append(
            "unknown components referenced in "
            "beneficiary_totals: "
            + ", ".join(unknown_components)
        )

    reserve_total = (
        policy_holdback
        + dispute_holdback
        + rounding_remainder
        + unallocated
    )

    plan_total = (
        beneficiary_total_sum
        + reserve_total
    )

    if not close_enough(
        policy_total,
        float(
            summary[
                "declared_policy_allocation_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_policy_allocation_total "
            "does not match policy allocations"
        )

    if not close_enough(
        distributed_total,
        float(
            summary[
                "declared_proportional_distribution_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_proportional_distribution_total "
            "does not match proportional entries"
        )

    if not close_enough(
        beneficiary_total_sum,
        float(
            summary[
                "declared_beneficiary_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_beneficiary_total does not "
            "match beneficiary_totals"
        )

    if not close_enough(
        reserve_total,
        float(
            summary[
                "declared_reserve_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_reserve_total does not "
            "match reserve"
        )

    if not close_enough(
        plan_total,
        float(
            summary[
                "declared_plan_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_plan_total does not "
            "match the plan"
        )

    if not close_enough(
        plan_total,
        allocatable,
    ):
        errors.append(
            "beneficiary totals plus reserve must "
            "equal the allocatable pool"
        )

    if (
        int(
            summary[
                "declared_beneficiary_count"
            ]
        )
        != len(totals)
    ):
        errors.append(
            "integrity_summary."
            "declared_beneficiary_count does not "
            "match beneficiary_totals length"
        )

    if (
        review["status"] != "approved"
        and downstream[
            "allocation_ledger_generation"
        ]
        == "eligible_after_approval"
    ):
        errors.append(
            "allocation ledger generation cannot "
            "be eligible before human review approval"
        )

    if (
        downstream[
            "automatic_reallocation_prohibited"
        ]
        is not True
    ):
        errors.append(
            "v0.3 requires automatic reallocation "
            "to remain prohibited"
        )

    if (
        downstream[
            "settlement_execution_prohibited"
        ]
        is not True
    ):
        errors.append(
            "v0.3 requires settlement execution "
            "to remain prohibited"
        )

    return errors


def validate(
    path: Path,
    validator: Draft202012Validator,
) -> list[str]:
    record = load_yaml(path)

    errors = schema_errors(
        validator,
        record,
    )

    if errors:
        return errors

    return semantic_errors(record)


def main() -> int:
    schema = load_json(SCHEMA_PATH)

    Draft202012Validator.check_schema(
        schema
    )

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    print(
        "=== Multi-Beneficiary Allocation Plan "
        "v0.3 Validation ==="
    )

    pass_errors = validate(
        PASS_EXAMPLE,
        validator,
    )

    if pass_errors:
        print(
            "[FAIL] expected pass: "
            f"{PASS_EXAMPLE.relative_to(ROOT)}"
        )

        for error in pass_errors:
            print(f"  - {error}")

        return 1

    print(
        "[PASS] "
        f"{PASS_EXAMPLE.relative_to(ROOT)}"
    )

    fail_errors = validate(
        FAIL_EXAMPLE,
        validator,
    )

    if not fail_errors:
        print(
            "[FAIL] invalid example was accepted: "
            f"{FAIL_EXAMPLE.relative_to(ROOT)}"
        )

        return 1

    print(
        "[PASS] expected rejection: "
        f"{FAIL_EXAMPLE.relative_to(ROOT)}"
    )

    for error in fail_errors:
        print(f"  - {error}")

    print(
        "\nAll v0.3 validations "
        "completed successfully."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
