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
    / "contribution-weight-resolution.schema.json"
)

PASS_EXAMPLE = (
    ROOT
    / "examples"
    / "pass"
    / "contribution-weight-resolution.example.yaml"
)

FAIL_EXAMPLE = (
    ROOT
    / "examples"
    / "fail"
    / "invalid-normalization.example.yaml"
)

EPSILON = 0.000001


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: root must be an object"
        )

    return data


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: root must be an object"
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


def duplicates(
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
            f"{('.'.join(str(part) for part "
            f"in error.absolute_path) or '<root>')}: "
            f"{error.message}"
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

    policy = record["policy_context"]
    contributions = record["input_contributions"]
    resolved = record["resolved_weights"]
    summary = record["integrity_summary"]
    review = record["human_review"]
    downstream = record["downstream_state"]

    contribution_ids = [
        item["contribution_id"]
        for item in contributions
    ]

    duplicate_contributions = duplicates(
        contribution_ids
    )

    if duplicate_contributions:
        errors.append(
            "duplicate contribution_id values: "
            + ", ".join(
                duplicate_contributions
            )
        )

    duplicate_beneficiaries = duplicates(
        [
            item["beneficiary_id"]
            for item in resolved
        ]
    )

    if duplicate_beneficiaries:
        errors.append(
            "duplicate resolved beneficiary_id values: "
            + ", ".join(
                duplicate_beneficiaries
            )
        )

    minimum_confidence = float(
        policy["minimum_evidence_confidence"]
    )

    input_by_id = {
        item["contribution_id"]: item
        for item in contributions
    }

    for index, item in enumerate(contributions):
        duplicate_factors = duplicates(
            [
                factor["factor_id"]
                for factor in item["factor_scores"]
            ]
        )

        if duplicate_factors:
            errors.append(
                f"input_contributions[{index}]: "
                "duplicate factor_id values: "
                + ", ".join(
                    duplicate_factors
                )
            )

        duplicate_adjustments = duplicates(
            [
                adjustment["adjustment_id"]
                for adjustment in item["adjustments"]
            ]
        )

        if duplicate_adjustments:
            errors.append(
                f"input_contributions[{index}]: "
                "duplicate adjustment_id values: "
                + ", ".join(
                    duplicate_adjustments
                )
            )

        calculated_base = 0.0

        for factor_index, factor in enumerate(
            item["factor_scores"]
        ):
            expected = (
                float(factor["raw_score"])
                * float(
                    factor["policy_coefficient"]
                )
            )

            declared = float(
                factor["weighted_score"]
            )

            if not close_enough(
                expected,
                declared,
            ):
                errors.append(
                    f"input_contributions[{index}]."
                    f"factor_scores[{factor_index}]: "
                    "weighted_score must equal "
                    "raw_score multiplied by "
                    "policy_coefficient"
                )

            calculated_base += declared

        declared_base = float(
            item["declared_base_score"]
        )

        if not close_enough(
            calculated_base,
            declared_base,
        ):
            errors.append(
                f"input_contributions[{index}]: "
                "declared_base_score does not match "
                "the sum of factor weighted scores"
            )

        calculated_adjustment = sum(
            float(adjustment["signed_value"])
            for adjustment in item["adjustments"]
        )

        declared_adjustment = float(
            item["declared_adjustment_total"]
        )

        if not close_enough(
            calculated_adjustment,
            declared_adjustment,
        ):
            errors.append(
                f"input_contributions[{index}]: "
                "declared_adjustment_total does not "
                "match adjustment values"
            )

        calculated_final = (
            declared_base
            + declared_adjustment
        )

        declared_final = float(
            item["declared_final_score"]
        )

        if calculated_final < -EPSILON:
            errors.append(
                f"input_contributions[{index}]: "
                "base score plus adjustments cannot "
                "produce a negative final score"
            )

        if not close_enough(
            calculated_final,
            declared_final,
        ):
            errors.append(
                f"input_contributions[{index}]: "
                "declared_final_score must equal "
                "declared_base_score plus "
                "declared_adjustment_total"
            )

        if (
            item["eligibility_status"]
            == "eligible"
            and float(
                item["evidence_confidence"]
            )
            < minimum_confidence
        ):
            errors.append(
                f"input_contributions[{index}]: "
                "eligible contribution does not meet "
                "minimum evidence confidence"
            )

    used_ids: list[str] = []
    score_total = 0.0
    weight_total = 0.0

    for index, item in enumerate(resolved):
        referenced: list[
            dict[str, Any]
        ] = []

        for contribution_id in item[
            "contribution_ids"
        ]:
            contribution = input_by_id.get(
                contribution_id
            )

            if contribution is None:
                errors.append(
                    f"resolved_weights[{index}]: "
                    "unknown contribution_id "
                    f"{contribution_id}"
                )
                continue

            referenced.append(contribution)
            used_ids.append(contribution_id)

            if (
                contribution["beneficiary_id"]
                != item["beneficiary_id"]
            ):
                errors.append(
                    f"resolved_weights[{index}]: "
                    f"contribution {contribution_id} "
                    "belongs to a different beneficiary"
                )

        if not referenced:
            continue

        expected_score = sum(
            float(
                source["declared_final_score"]
            )
            for source in referenced
        )

        declared_score = float(
            item["final_score"]
        )

        if not close_enough(
            expected_score,
            declared_score,
        ):
            errors.append(
                f"resolved_weights[{index}]: "
                "final_score does not match "
                "referenced contribution final scores"
            )

        expected_confidence = min(
            float(
                source["evidence_confidence"]
            )
            for source in referenced
        )

        if not close_enough(
            expected_confidence,
            float(item["confidence"]),
        ):
            errors.append(
                f"resolved_weights[{index}]: "
                "confidence must equal the lowest "
                "evidence confidence among referenced "
                "contributions"
            )

        statuses = {
            source["eligibility_status"]
            for source in referenced
        }

        if (
            "excluded_by_policy" in statuses
            and item["resolution_status"]
            != "excluded_by_policy"
        ):
            errors.append(
                f"resolved_weights[{index}]: "
                "excluded contribution cannot receive "
                "a proposed or held weight"
            )

        if (
            "held_for_review" in statuses
            and item["resolution_status"]
            == "proposed"
        ):
            errors.append(
                f"resolved_weights[{index}]: "
                "held contribution cannot be resolved "
                "as proposed"
            )

        if (
            item["resolution_status"]
            == "excluded_by_policy"
        ):
            if not close_enough(
                declared_score,
                0.0,
            ):
                errors.append(
                    f"resolved_weights[{index}]: "
                    "excluded_by_policy requires "
                    "final_score equal to zero"
                )

            if not close_enough(
                float(
                    item["normalized_weight"]
                ),
                0.0,
            ):
                errors.append(
                    f"resolved_weights[{index}]: "
                    "excluded_by_policy requires "
                    "normalized_weight equal to zero"
                )
        else:
            score_total += declared_score
            weight_total += float(
                item["normalized_weight"]
            )

    duplicate_usage = duplicates(used_ids)

    if duplicate_usage:
        errors.append(
            "contribution_ids assigned to multiple "
            "resolved beneficiaries: "
            + ", ".join(
                duplicate_usage
            )
        )

    unresolved_ids = summary[
        "unresolved_contribution_ids"
    ]

    unknown_unresolved = sorted(
        set(unresolved_ids)
        - set(contribution_ids)
    )

    if unknown_unresolved:
        errors.append(
            "unknown unresolved_contribution_ids: "
            + ", ".join(
                unknown_unresolved
            )
        )

    overlap = sorted(
        set(used_ids)
        & set(unresolved_ids)
    )

    if overlap:
        errors.append(
            "contributions cannot be both resolved "
            "and unresolved: "
            + ", ".join(overlap)
        )

    missing = sorted(
        set(contribution_ids)
        - (
            set(used_ids)
            | set(unresolved_ids)
        )
    )

    if missing:
        errors.append(
            "input contributions missing from "
            "resolved or unresolved sets: "
            + ", ".join(missing)
        )

    if score_total <= EPSILON:
        errors.append(
            "at least one non-excluded resolved score "
            "must be greater than zero"
        )
    else:
        for index, item in enumerate(resolved):
            if (
                item["resolution_status"]
                == "excluded_by_policy"
            ):
                continue

            expected_weight = (
                float(item["final_score"])
                / score_total
            )

            if not close_enough(
                expected_weight,
                float(
                    item["normalized_weight"]
                ),
            ):
                errors.append(
                    f"resolved_weights[{index}]: "
                    "normalized_weight must equal "
                    "final_score divided by the total "
                    "non-excluded final score"
                )

    if not close_enough(
        score_total,
        float(
            summary[
                "declared_final_score_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_final_score_total does not "
            "match resolved scores"
        )

    if not close_enough(
        weight_total,
        float(
            summary[
                "declared_normalized_weight_total"
            ]
        ),
    ):
        errors.append(
            "integrity_summary."
            "declared_normalized_weight_total does "
            "not match resolved weights"
        )

    if not close_enough(
        weight_total,
        1.0,
    ):
        errors.append(
            "non-excluded normalized weights "
            "must sum to 1.0"
        )

    if (
        int(
            summary[
                "declared_resolved_beneficiary_count"
            ]
        )
        != len(resolved)
    ):
        errors.append(
            "integrity_summary."
            "declared_resolved_beneficiary_count "
            "does not match resolved_weights length"
        )

    if (
        review["status"] != "approved"
        and downstream[
            "allocation_ledger_generation"
        ]
        == "eligible_after_approval"
    ):
        errors.append(
            "allocation ledger generation cannot be "
            "eligible before human approval"
        )

    if (
        downstream[
            "automatic_right_creation_prohibited"
        ]
        is not True
    ):
        errors.append(
            "v0.2 requires automatic right creation "
            "to remain prohibited"
        )

    if (
        downstream[
            "settlement_execution_prohibited"
        ]
        is not True
    ):
        errors.append(
            "v0.2 requires settlement execution "
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
        "=== Contribution Weight Resolution "
        "v0.2 Validation ==="
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
        f"[PASS] "
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
        "\nAll v0.2 validations "
        "completed successfully."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
