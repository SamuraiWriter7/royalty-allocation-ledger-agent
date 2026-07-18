# Royalty Allocation Ledger Agent

**Audit-ready specifications for translating verified contribution evidence into explainable multi-beneficiary royalty allocations, dispute holdbacks, and non-executable settlement handoffs.**

`royalty-allocation-ledger-agent` defines a record-oriented protocol for royalty allocation workflows in which evidence, contribution weights, allocation policies, disputes, held amounts, settlement readiness, and audit results must remain traceable.

The repository does **not** define an autonomous payment agent. It defines the ledgers and boundaries required before an authorized payment system or human operator may execute settlement.

---

## Status

Current specification:

```text
v0.5.0-candidate
```

Implemented layers:

```text
v0.1  Allocation Ledger Record
v0.2  Contribution Weight Resolution
v0.3  Multi-Beneficiary Allocation Plan
v0.4  Dispute and Holdback Ledger
v0.5  Settlement Handoff and Royalty Audit
```

The v0.1–v0.5 sequence forms the first complete specification arc.

---

## Core Principle

> Evidence must precede weighting, weighting must precede allocation, disputes must be scoped, held amounts must remain conserved, and settlement execution must remain outside the allocation agent.

The protocol separates six concepts that are often incorrectly collapsed into one operation:

```text
Evidence
   ≠
Contribution Weight
   ≠
Allocation Plan
   ≠
Holdback Resolution
   ≠
Settlement Handoff
   ≠
Executed Payment
```

Each transition produces its own auditable record.

---

## Why This Repository Exists

Royalty allocation becomes difficult when a system must support:

- multiple human and organizational beneficiaries
- origin and derivative contributions
- policy-defined fees and shared funds
- incomplete or disputed attribution
- partial holds instead of global freezes
- retroactive corrections
- identity and endpoint verification
- tax and employment boundaries
- bank, internal-ledger, or x402 settlement routes
- post-handoff reconciliation
- human approval and audit evidence

A single opaque percentage table is not sufficient.

This repository treats royalty allocation as a sequence of typed, verifiable records rather than one irreversible calculation.

---

## End-to-End Flow

```text
Verified Source Records
        ↓
v0.1 Allocation Ledger Record
        ↓
v0.2 Contribution Weight Resolution
        ↓
v0.3 Multi-Beneficiary Allocation Plan
        ↓
v0.4 Dispute and Holdback Ledger
        ↓
v0.5 Settlement Handoff and Royalty Audit
        ↓
Authorized Payment System or Human Operator
        ↓
External Settlement Receipts
```

The allocation agent may prepare records through v0.5, but it must not execute payment.

---

## Design Principles

### 1. Evidence Before Allocation

A beneficiary, weight, adjustment, hold, release, or settlement instruction must reference verified source records.

The protocol does not create attribution merely because a payment is desired.

### 2. Rights Creation Is Prohibited

The allocation agent may translate approved rights and contribution records into weights and amounts.

It must not invent legal ownership, authorship, employment status, licensing rights, or beneficiary identity.

### 3. Disputes Must Be Scoped

A dispute affecting one beneficiary or one portion of an allocation must not automatically freeze unrelated allocations.

```text
Unscoped global freeze
        ✕
Explicit disputed amount
        ✓
Explicit undisputed amount
        ✓
```

### 4. Held Amounts Must Not Disappear

Reserved and disputed amounts remain visible until they are:

- released to the beneficiary allocation
- retained under an active hold
- returned to an unallocated pool
- superseded by a verified correction record

### 5. Settlement Handoff Is Not Payment

The protocol may generate a settlement instruction draft and an audit report.

Only an authorized settlement target may execute payment.

### 6. Human Approval Remains Mandatory

The agent must not approve its own:

- allocation ledger
- contribution-weight resolution
- allocation plan
- dispute resolution
- holdback release
- settlement handoff

---

## Specification Layers

## v0.1 — Allocation Ledger Record

v0.1 records an already-supported allocation state without creating new rights or weights.

It captures:

- royalty-pool context
- beneficiary identities or references
- gross allocations
- payable amounts
- held amounts
- evidence references
- hold reasons
- approval state
- safety boundaries

### v0.1 Conservation Rule

For each beneficiary:

```text
gross allocation
    =
payable amount
    +
held amount
```

For the full pool:

```text
gross pool
    =
distributable amount
    +
excluded amount
```

The ledger records the state of allocation. It is not a payment instruction.

---

## v0.2 — Contribution Weight Resolution

v0.2 converts verified contribution evidence and policy multipliers into provisional normalized weights.

It captures:

- attribution references
- contribution components
- raw scores
- policy multipliers
- weighted scores
- policy adjustments
- adjusted scores
- included, held, and excluded states
- normalized weights
- normalization residuals
- evidence and approval records

### v0.2 Calculation Flow

```text
raw score
    ×
policy multiplier
    =
weighted component score
```

```text
component total
    +
policy adjustments
    =
adjusted score
```

```text
beneficiary adjusted score
    ÷
eligible adjusted-score total
    =
normalized weight
```

A held beneficiary may remain inside normalization when the policy uses `reserve_in_normalization`. This preserves the held share and prevents silent redistribution.

### v0.2 Boundary

v0.2 resolves weights only from verified attribution.

It does not:

- determine legal ownership
- create new attribution
- redistribute held weights
- calculate a final payment amount
- execute settlement

---

## v0.3 — Multi-Beneficiary Allocation Plan

v0.3 converts approved weights and allocation policy rules into a complete multi-beneficiary amount plan.

It supports:

- fixed amounts
- fixed rates
- proportional weights
- pooled weights
- community or public funds
- platform fees
- minimum and maximum constraints
- rounding policies
- remainder policies
- payable candidates
- reserved allocations
- excluded allocations

### v0.3 Allocation Order

A typical policy may use:

```text
Distributable Royalty Pool
        ↓
Fixed Allocations
        ↓
Proportional Pool
        ↓
Approved Contribution Weights
        ↓
Rounding and Remainder Handling
        ↓
Payable Candidates and Reserved Amounts
```

### v0.3 Conservation Rules

```text
final plan total
    =
fixed allocation total
    +
proportional allocation total
```

```text
final plan total
    =
payable candidate total
    +
reserved total
```

```text
distributable amount
    =
final plan total
    +
unallocated total
    +
rounding residual
```

### Reference Example

```text
Distributable pool:       100,000 JPY
Fixed allocations:         5,000 JPY
Proportional pool:         95,000 JPY
Payable candidates:        81,000 JPY
Reserved for review:       19,000 JPY
Final plan total:         100,000 JPY
```

The reserved 19,000 JPY remains part of the beneficiary plan and must not be redistributed.

---

## v0.4 — Dispute and Holdback Ledger

v0.4 isolates disputed allocation amounts while allowing verified and unaffected portions to continue.

It supports:

- full-allocation disputes
- partial-allocation disputes
- explicit disputed and undisputed amounts
- claimant records
- evidence requests
- review deadlines
- partial resolutions
- partial releases
- continued holds
- returns to the unallocated pool
- correction adjustments
- immutable release-event histories
- superseding holdback ledgers

### Partial Hold Principle

```text
Original reserved amount: 19,000 JPY
        ↓
Disputed amount:            5,000 JPY
Undisputed amount:         14,000 JPY
        ↓
Released to allocation:    14,000 JPY
Current holdback:            5,000 JPY
```

A limited dispute must not freeze the entire 19,000 JPY when only 5,000 JPY is contested.

### v0.4 Conservation Rules

```text
effective holdback amount
    =
source reserved amount
    +
correction adjustment
```

```text
effective holdback amount
    =
released amount
    +
current held amount
    +
returned-to-pool amount
```

### Release Boundary

```text
Holdback Release
        ≠
Settlement Readiness
        ≠
Executed Payment
```

A released amount returns to the allocation lifecycle. It must still pass settlement, identity, endpoint, compliance, and approval controls.

---

## v0.5 — Settlement Handoff and Royalty Audit

v0.5 converts approved allocations and approved holdback releases into non-executable settlement instructions.

It supports:

- settlement batches
- beneficiary settlement instructions
- approved holdback-release references
- active-holdback exclusion
- tokenized bank endpoints
- payment-token endpoints
- x402 wallet endpoints
- internal-ledger routes
- identity verification status
- tax boundaries
- employment boundaries
- blocking reasons
- authorized handoff targets
- reconciliation records
- royalty audit reports
- external settlement-receipt references

### v0.5 Settlement Flow

```text
Approved Allocation
        ↓
Approved Holdback Release
        ↓
Endpoint Verification
        ↓
Identity and Compliance Boundaries
        ↓
Settlement Instruction Draft
        ↓
Royalty Audit
        ↓
Human Approval
        ↓
Authorized Handoff Target
```

### v0.5 Conservation Rules

For each instruction:

```text
planned amount
    =
settlement amount
    +
current held amount
    +
returned-to-pool amount
```

For the settlement batch:

```text
approved allocation total
    =
settlement-ready total
    +
current holdback total
    +
returned-to-pool total
```

For reconciliation:

```text
expected settlement total
    =
executed total
    +
failed total
    +
pending total
```

### Reference Example

```text
Approved allocation total: 100,000 JPY
Settlement-ready total:     95,000 JPY
Current holdback total:       5,000 JPY
Returned to pool:                 0 JPY
```

### Execution Boundary

```text
Settlement Instruction
        ≠
Settlement Handoff
        ≠
Executed Payment
```

The allocation agent may prepare and audit a handoff record. It must not execute the payment.

---

## Repository Structure

```text
royalty-allocation-ledger-agent/
├── README.md
├── CHANGELOG.md
├── schemas/
│   ├── allocation-ledger-record.schema.json
│   ├── contribution-weight-resolution.schema.json
│   ├── multi-beneficiary-allocation-plan.schema.json
│   ├── dispute-holdback-ledger.schema.json
│   └── settlement-handoff-record.schema.json
├── examples/
│   └── pass/
│       ├── allocation-ledger-record.example.yaml
│       ├── contribution-weight-resolution.example.yaml
│       ├── multi-beneficiary-allocation-plan.example.yaml
│       ├── dispute-holdback-ledger.example.yaml
│       └── settlement-handoff-record.example.yaml
├── policies/
│   ├── default-contribution-weight-policy.example.yaml
│   ├── default-multi-beneficiary-allocation-policy.example.yaml
│   ├── default-dispute-holdback-policy.example.yaml
│   └── default-settlement-handoff-policy.example.yaml
└── scripts/
    └── validate_examples.py
```

---

## Schema and Example Matrix

| Version | Record | Schema | Passing Example |
|---|---|---|---|
| v0.1 | Allocation Ledger Record | `schemas/allocation-ledger-record.schema.json` | `examples/pass/allocation-ledger-record.example.yaml` |
| v0.2 | Contribution Weight Resolution | `schemas/contribution-weight-resolution.schema.json` | `examples/pass/contribution-weight-resolution.example.yaml` |
| v0.3 | Multi-Beneficiary Allocation Plan | `schemas/multi-beneficiary-allocation-plan.schema.json` | `examples/pass/multi-beneficiary-allocation-plan.example.yaml` |
| v0.4 | Dispute and Holdback Ledger | `schemas/dispute-holdback-ledger.schema.json` | `examples/pass/dispute-holdback-ledger.example.yaml` |
| v0.5 | Settlement Handoff and Royalty Audit | `schemas/settlement-handoff-record.schema.json` | `examples/pass/settlement-handoff-record.example.yaml` |

---

## Quick Start

### Requirements

- Python 3.11 or later
- `jsonschema`
- `PyYAML`

Install the validation dependencies:

```bash
python -m pip install jsonschema PyYAML
```

### Validate All Examples

```bash
python scripts/validate_examples.py
```

A successful run prints:

```text
=== Royalty Allocation Ledger Agent Validation ===

[validate] Allocation Ledger Record
[schema-ok]
[semantic-ok]

[validate] Contribution Weight Resolution
[schema-ok]
[semantic-ok]

[validate] Multi-Beneficiary Allocation Plan
[schema-ok]
[semantic-ok]

[validate] Dispute and Holdback Ledger
[schema-ok]
[semantic-ok]

[validate] Settlement Handoff and Royalty Audit
[schema-ok]
[semantic-ok]

All Royalty Allocation Ledger Agent examples are valid.
```

### Check Python Syntax

```bash
python -m py_compile scripts/validate_examples.py
```

### Check a JSON Schema File

```bash
python -m json.tool \
  schemas/settlement-handoff-record.schema.json \
  > /dev/null
```

### Check a YAML Example

```bash
python - <<'PY'
from pathlib import Path
import yaml

path = Path(
    "examples/pass/settlement-handoff-record.example.yaml"
)

document = yaml.safe_load(
    path.read_text(encoding="utf-8")
)

print(document["schema_version"])
print(document["handoff_id"])
PY
```

---

## Validation Model

The validation script performs two layers of validation.

### 1. JSON Schema Validation

This verifies:

- required fields
- field types
- enumerated values
- date-time and URI formats
- conditional requirements
- additional-property restrictions
- minimum values
- fixed safety flags

### 2. Semantic Validation

This verifies relationships that cannot be fully expressed by field-level schemas, including:

- amount conservation
- normalized-weight totals
- duplicate identifiers
- evidence-reference membership
- source-record consistency
- hold and release consistency
- plan and policy totals
- dispute-scope conservation
- holdback-event totals
- settlement-batch reconciliation
- approval-state consistency
- mandatory safety boundaries

A document is considered valid only when both layers pass.

---

## Record Immutability and Supersession

Published records should be treated as append-only audit artifacts.

A correction should create a new record that references the previous record rather than silently overwriting it.

Examples include:

- a corrected contribution-weight resolution
- a revised allocation plan
- a superseding holdback ledger
- a superseding settlement handoff

The original record should remain available for audit and lineage reconstruction.

---

## Evidence Model

Every material decision should be traceable to source records.

Typical source records include:

- origin records
- contribution-attribution records
- license constraints
- allocation policies
- dispute records
- identity records
- endpoint-verification records
- tax reviews
- employment reviews
- human approval receipts

Evidence references should state:

- source record type
- source record identifier
- relationship to the current decision
- verification state
- optional explanation

The current specification assumes source verification is performed by an upstream trusted process. It does not define cryptographic verification itself.

---

## Privacy and Credential Boundary

The protocol should store references, tokens, and verification states—not raw secrets.

Do not include:

- full bank account numbers
- passwords
- private keys
- wallet seed phrases
- secret API credentials
- unrestricted personal identity documents
- payment-provider authentication tokens

Use protected references such as:

- tokenized bank routes
- payment endpoint identifiers
- x402 wallet references
- internal-ledger identifiers
- separately governed identity-record identifiers

---

## Integration Boundary

v0.5 may hand records to systems such as:

- `agentic-royalty-path-standard`
- bank settlement gateways
- x402-compatible payment routes
- internal accounting ledgers
- human-operated settlement workflows

The handoff target remains responsible for:

- final authorization
- payment-provider authentication
- regulatory compliance
- transaction execution
- execution receipts
- failure handling
- chargeback or reversal handling
- final reconciliation

---

## Non-Goals

This repository does not define:

- autonomous legal ownership determination
- autonomous authorship determination
- autonomous dispute adjudication
- tax-law interpretation
- employment classification
- identity verification procedures
- bank account verification procedures
- executable payment-provider credentials
- payment execution
- blockchain consensus
- currency conversion
- securities settlement
- debt collection
- court-enforceable contracts

These concerns may be referenced as external boundaries or records, but they remain outside the allocation agent.

---

## Safety Boundaries

Across v0.1–v0.5, the following rules remain mandatory:

- evidence is required
- verified attribution is required before weighting
- rights creation is prohibited
- attribution rewriting is prohibited
- held-weight redistribution is prohibited
- unscoped global freezes are prohibited
- automatic dispute resolution is prohibited
- active holdbacks must be excluded from settlement
- raw payment credentials are prohibited
- autonomous payment is prohibited
- agent self-approval is prohibited
- human approval is required

---

## Versioning

This repository currently uses candidate specification versions.

```text
0.1.0-candidate
0.2.0-candidate
0.3.0-candidate
0.4.0-candidate
0.5.0-candidate
```

Candidate versions may change before a stable `1.0.0` release.

Breaking schema changes should increment the specification version and provide migration notes.

---

## First Arc Summary

```text
v0.1
Record supported allocation amounts
        ↓
v0.2
Resolve evidence-backed contribution weights
        ↓
v0.3
Generate a multi-beneficiary allocation plan
        ↓
v0.4
Isolate disputes and preserve holdbacks
        ↓
v0.5
Prepare an audit-ready settlement handoff
```

The result is not an autonomous treasury.

It is a traceable allocation protocol in which every major transformation has a record, every conserved amount can be recomputed, and every execution boundary remains explicit.

---

## License

See the repository's `LICENSE` file for applicable terms.
