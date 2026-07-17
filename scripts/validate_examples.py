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
    / "allocation-ledger-record.schema.json"
)

PASS_FILE = (
    ROOT
    / "examples"
    / "pass"
    / "allocation-ledger-record.example.yaml"
)

FAIL_FILE = (
    ROOT
    / "examples"
    / "fail"
    / "missing-evidence.example.yaml"
)

EPSILON = 0.000001


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: root value must be an object"
        )

    return data


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: root value must be an object"
        )

    return data


def close_enough(
    left: float,
    right: float,
) -> bool:
    return math.isclose(
        left,
        right,
        abs_tol=EPSILON,
        rel_tol=0.0,
    )


def duplicate_values(
    values: list[str],
) -> list[str]:
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
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        )
        for error in sorted(
            validator.iter_errors(record),
            key=lambda item: list(
                item.absolute_path
            ),
        )
    ]


def semantic_errors(
    record: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    pool = record["royalty_pool"]
    beneficiaries = record["beneficiaries"]
    reserve = record["reserve"]
    summary = record["integrity_summary"]
    review = record["human_review"]
    settlement = record["settlement_state"]

    gross = float(pool["gross_amount"])
    deductions = float(pool["deduction_amount"])
    allocatable = float(
        pool["allocatable_amount"]
    )

    if not close_enough(
        gross - deductions,
        allocatable,
    ):
        errors.append(
            "royalty_pool.allocatable_amount must equal "
            "gross_amount minus deduction_amount"
        )

    beneficiary_ids = [
        item["beneficiary_id"]
        for item in beneficiaries
    ]

    duplicates = duplicate_values(
        beneficiary_ids
    )

    if duplicates:
        errors.append(
            "duplicate beneficiary_id values: "
            + ", ".join(duplicates)
        )

    weight_total = sum(
        float(item["contribution_weight"])
        for item in beneficiaries
    )

    gross_allocated = sum(
        float(
            item["gross_allocation_amount"]
        )
        for item in beneficiaries
    )

    payable_total = sum(
        float(item["payable_amount"])
        for item in beneficiaries
    )

    held_total = sum(
        float(item["held_amount"])
        for item in beneficiaries
    )

    for index, item in enumerate(
        beneficiaries
    ):
        gross_amount = float(
            item["gross_allocation_amount"]
        )

        payable_amount = float(
            item["payable_amount"]
        )

        held_amount = float(
            item["held_amount"]
        )

        if not close_enough(
            gross_amount,
            payable_amount + held_amount,
        ):
            errors.append(
                f"beneficiaries[{index}]: "
                "gross_allocation_amount must equal "
                "payable_amount plus held_amount"
            )

        if (
            item["allocation_status"]
            == "held_for_review"
            and held_amount <= 0
        ):
            errors.append(
                f"beneficiaries[{index}]: "
                "held_for_review requires held_amount "
                "greater than zero"
            )

        if (
            item["allocation_status"]
            == "payable_after_approval"
            and held_amount > 0
        ):
            errors.append(
                f"beneficiaries[{index}]: "
                "payable_after_approval cannot "
                "contain a held amount"
            )

    if not close_enough(
        weight_total,
        float(
            summary[
                "declared_weight_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_weight_total does not match "
            "beneficiary weights"
        )

    if not close_enough(
        payable_total,
        float(
            summary[
                "declared_payable_amount"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_payable_amount does not match "
            "beneficiary payable amounts"
        )

    if not close_enough(
        held_total,
        float(
            summary[
                "declared_held_amount"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_held_amount does not match "
            "beneficiary held amounts"
        )

    if not close_enough(
        gross_allocated,
        float(
            summary[
                "declared_allocated_amount"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_allocated_amount does not match "
            "beneficiary allocations"
        )

    reserve_total = (
        float(reserve["holdback_amount"])
        + float(
            reserve[
                "rounding_remainder_amount"
            ]
        )
        + float(
            reserve["unallocated_amount"]
        )
    )

    if not close_enough(
        gross_allocated + reserve_total,
        allocatable,
    ):
        errors.append(
            "beneficiary allocations plus all "
            "reserve amounts must equal "
            "royalty_pool.allocatable_amount"
        )

    if (
        review["status"] != "approved"
        and settlement["status"]
        == "approved_for_handoff"
    ):
        errors.append(
            "settlement cannot be "
            "approved_for_handoff before "
            "human review approval"
        )

    if (
        settlement["execution_prohibited"]
        is not True
    ):
        errors.append(
            "v0.1 requires "
            "settlement_state."
            "execution_prohibited to remain true"
        )

    return errors


def validate_expected_pass(
    validator: Draft202012Validator,
    path: Path,
) -> bool:
    record = load_yaml(path)

    errors = schema_errors(
        validator,
        record,
    )

    if not errors:
        errors.extend(
            semantic_errors(record)
        )

    if errors:
        print(
            "[FAIL] expected pass: "
            f"{path.relative_to(ROOT)}"
        )

        for error in errors:
            print(f"  - {error}")

        return False

    print(
        f"[PASS] {path.relative_to(ROOT)}"
    )

    return True


def validate_expected_fail(
    validator: Draft202012Validator,
    path: Path,
) -> bool:
    record = load_yaml(path)

    errors = schema_errors(
        validator,
        record,
    )

    if not errors:
        errors = semantic_errors(record)

    if errors:
        print(
            "[PASS] expected rejection: "
            f"{path.relative_to(ROOT)}"
        )

        for error in errors:
            print(f"  - {error}")

        return True

    print(
        "[FAIL] invalid example was accepted: "
        f"{path.relative_to(ROOT)}"
    )

    return False


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
        "=== Royalty Allocation Ledger Agent "
        "v0.1 Validation ==="
    )

    results = [
        validate_expected_pass(
            validator,
            PASS_FILE,
        ),
        validate_expected_fail(
            validator,
            FAIL_FILE,
        ),
    ]

    if all(results):
        print(
            "\nAll validations completed "
            "successfully."
        )
        return 0

    print("\nValidation failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
