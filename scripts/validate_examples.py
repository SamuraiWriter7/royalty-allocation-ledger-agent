#!/usr/bin/env python3
"""
Validate Allocation Ledger Record examples.

Validation layers:
1. JSON Schema validation
2. Allocation integrity validation
3. Approval and safety-boundary validation
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
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

EXAMPLE_DIRECTORY = ROOT / "examples" / "pass"


def load_document(path: Path) -> Any:
    """Load a JSON or YAML document."""

    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() == ".json":
            return json.load(file)

        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(file)

    raise ValueError(f"Unsupported file type: {path}")


def decimal_value(value: Any, field_name: str) -> Decimal:
    """Convert an amount to Decimal without accepting invalid values."""

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(
            f"{field_name} must be a valid numeric amount: {value!r}"
        ) from error


def validate_schema(
    document: Any,
    schema: dict[str, Any],
) -> list[str]:
    """Validate a document against the JSON Schema."""

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


def validate_beneficiaries(
    document: dict[str, Any],
) -> list[str]:
    """Validate beneficiary-level allocation integrity."""

    errors: list[str] = []
    beneficiary_ids: set[str] = set()

    for index, beneficiary in enumerate(
        document.get("beneficiaries", [])
    ):
        prefix = f"beneficiaries[{index}]"

        beneficiary_id = beneficiary.get("beneficiary_id")

        if beneficiary_id in beneficiary_ids:
            errors.append(
                f"[semantic-error] {prefix}.beneficiary_id: "
                f"duplicate beneficiary '{beneficiary_id}'"
            )
        else:
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

        if gross != payable + held:
            errors.append(
                f"[semantic-error] {prefix}: gross_allocation "
                f"must equal payable_amount + held_amount "
                f"({gross} != {payable} + {held})"
            )

        evidence_refs = beneficiary.get("evidence_refs", [])

        if not evidence_refs:
            errors.append(
                f"[semantic-error] {prefix}.evidence_refs: "
                "at least one verified evidence reference is required"
            )

        evidence_keys: set[tuple[str, str]] = set()

        for evidence_index, evidence in enumerate(evidence_refs):
            evidence_key = (
                str(evidence.get("record_type")),
                str(evidence.get("record_id")),
            )

            if evidence_key in evidence_keys:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.evidence_refs[{evidence_index}]: "
                    f"duplicate evidence reference {evidence_key}"
                )

            evidence_keys.add(evidence_key)

            if evidence.get("verified") is not True:
                errors.append(
                    f"[semantic-error] "
                    f"{prefix}.evidence_refs[{evidence_index}].verified: "
                    "allocation evidence must be verified"
                )

        hold_reasons = beneficiary.get("hold_reasons", [])
        allocation_status = beneficiary.get("allocation_status")

        if held > 0 and not hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "a positive held_amount requires at least one hold reason"
            )

        if held == 0 and hold_reasons:
            errors.append(
                f"[semantic-error] {prefix}.hold_reasons: "
                "hold reasons must not be present when held_amount is zero"
            )

        if held == 0 and payable > 0:
            expected_status = "payable"

            if allocation_status != expected_status:
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    f"expected '{expected_status}' when the entire "
                    "allocation is payable"
                )

        if held > 0 and payable > 0:
            expected_status = "partially_held"

            if allocation_status != expected_status:
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    f"expected '{expected_status}' when the allocation "
                    "contains both payable and held amounts"
                )

        if held > 0 and payable == 0:
            expected_status = "fully_held"

            if allocation_status != expected_status:
                errors.append(
                    f"[semantic-error] {prefix}.allocation_status: "
                    f"expected '{expected_status}' when the entire "
                    "allocation is held"
                )

        if allocation_status == "rejected" and gross != 0:
            errors.append(
                f"[semantic-error] {prefix}: a rejected allocation "
                "must have a gross allocation of zero"
            )

        if beneficiary.get("beneficiary_type") == "other":
            explanation = beneficiary.get("explanation")

            if not explanation:
                errors.append(
                    f"[semantic-error] {prefix}.explanation: "
                    "beneficiary_type 'other' requires an explanation"
                )

    return errors


def validate_totals(
    document: dict[str, Any],
) -> list[str]:
    """Validate ledger-level amount totals."""

    errors: list[str] = []

    beneficiaries = document.get("beneficiaries", [])
    totals = document.get("totals", {})
    royalty_pool = document.get("royalty_pool", {})

    calculated_gross = sum(
        (
            decimal_value(
                beneficiary.get("gross_allocation", 0),
                "gross_allocation",
            )
            for beneficiary in beneficiaries
        ),
        Decimal("0"),
    )

    calculated_payable = sum(
        (
            decimal_value(
                beneficiary.get("payable_amount", 0),
                "payable_amount",
            )
            for beneficiary in beneficiaries
        ),
        Decimal("0"),
    )

    calculated_held = sum(
        (
            decimal_value(
                beneficiary.get("held_amount", 0),
                "held_amount",
            )
            for beneficiary in beneficiaries
        ),
        Decimal("0"),
    )

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
        royalty_pool.get("distributable_amount", 0),
        "royalty_pool.distributable_amount",
    )

    gross_pool = decimal_value(
        royalty_pool.get("gross_amount", 0),
        "royalty_pool.gross_amount",
    )

    excluded_amount = decimal_value(
        royalty_pool.get("excluded_amount", 0),
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
            f"declared {declared_payable}, "
            f"calculated {calculated_payable}"
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
            "+ rounding_adjustment "
            f"({distributable} != {expected_distributable})"
        )

    if distributable > gross_pool:
        errors.append(
            "[semantic-error] royalty_pool.distributable_amount: "
            "must not exceed gross_amount"
        )

    if gross_pool != distributable + excluded_amount:
        errors.append(
            "[semantic-error] royalty_pool: gross_amount must equal "
            "distributable_amount + excluded_amount"
        )

    return errors


def validate_approval(
    document: dict[str, Any],
) -> list[str]:
    """Validate approval and ledger-status relationships."""

    errors: list[str] = []

    approval = document.get("approval", {})
    approval_status = approval.get("status")
    ledger_status = document.get("ledger_status")

    if approval_status == "pending":
        allowed_statuses = {
            "draft",
            "pending_human_approval",
        }

        if ledger_status not in allowed_statuses:
            errors.append(
                "[semantic-error] ledger_status: pending approval "
                "requires 'draft' or 'pending_human_approval'"
            )

    if approval_status == "approved":
        if ledger_status != "approved":
            errors.append(
                "[semantic-error] ledger_status: approved human review "
                "requires ledger_status 'approved'"
            )

    if approval_status == "rejected":
        if ledger_status != "rejected":
            errors.append(
                "[semantic-error] ledger_status: rejected human review "
                "requires ledger_status 'rejected'"
            )

    beneficiary_approval_states = {
        beneficiary.get("approval_status")
        for beneficiary in document.get("beneficiaries", [])
    }

    if approval_status == "approved":
        if beneficiary_approval_states - {"approved"}:
            errors.append(
                "[semantic-error] beneficiaries: all beneficiary "
                "allocations must be approved before the ledger "
                "can be approved"
            )

    return errors


def validate_safety_boundary(
    document: dict[str, Any],
) -> list[str]:
    """Ensure mandatory agent boundaries remain active."""

    errors: list[str] = []

    safety_boundary = document.get("safety_boundary", {})

    required_true_fields = [
        "evidence_required",
        "rights_creation_prohibited",
        "autonomous_payment_prohibited",
        "human_approval_required",
    ]

    for field_name in required_true_fields:
        if safety_boundary.get(field_name) is not True:
            errors.append(
                f"[semantic-error] safety_boundary.{field_name}: "
                "must remain true"
            )

    return errors


def validate_document(
    document: dict[str, Any],
    schema: dict[str, Any],
) -> list[str]:
    """Run all validation layers."""

    errors: list[str] = []

    errors.extend(validate_schema(document, schema))

    if errors:
        return errors

    errors.extend(validate_beneficiaries(document))
    errors.extend(validate_totals(document))
    errors.extend(validate_approval(document))
    errors.extend(validate_safety_boundary(document))

    return errors


def find_examples() -> list[Path]:
    """Return all supported pass examples."""

    examples: list[Path] = []

    for pattern in ("*.yaml", "*.yml", "*.json"):
        examples.extend(EXAMPLE_DIRECTORY.glob(pattern))

    return sorted(examples)


def main() -> int:
    """Validate all Allocation Ledger Record examples."""

    print("=== Royalty Allocation Ledger Agent Validation ===")
    print()

    if not SCHEMA_PATH.exists():
        print(f"[fatal] Schema not found: {SCHEMA_PATH}")
        return 1

    schema = load_document(SCHEMA_PATH)

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:
        print(f"[fatal] Invalid JSON Schema: {error}")
        return 1

    example_paths = find_examples()

    if not example_paths:
        print(f"[fatal] No examples found in: {EXAMPLE_DIRECTORY}")
        return 1

    failed = False

    for example_path in example_paths:
        relative_path = example_path.relative_to(ROOT)

        print("[validate] Allocation Ledger Record")
        print(f"  schema : {SCHEMA_PATH.relative_to(ROOT)}")
        print(f"  example: {relative_path}")

        try:
            document = load_document(example_path)
            errors = validate_document(document, schema)
        except Exception as error:
            print(f"[fatal] {relative_path}: {error}")
            print()
            failed = True
            continue

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

    print("All Allocation Ledger Record examples are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
