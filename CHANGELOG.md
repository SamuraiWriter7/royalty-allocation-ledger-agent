# Changelog

All notable changes to `royalty-allocation-ledger-agent` are documented in this file.

The format is inspired by Keep a Changelog, and the project uses candidate semantic versions while the first specification arc remains under review.

---

## [Unreleased]

### Planned

- Cross-record integration fixtures covering v0.1 through v0.5.
- Failing examples for negative validation tests.
- Formal migration guidance between candidate schema versions.
- Optional cryptographic digest fields for immutable record verification.
- Stable v1.0 review after the first-arc schemas and validators mature.

---

## [0.5.0-candidate] - 2026-07-18

### Added

- Settlement Handoff and Royalty Audit Record specification.
- Settlement batch records.
- Non-executable beneficiary settlement instructions.
- Approved allocation-plan references.
- Approved holdback-release references.
- Current-holdback exclusion.
- Returned-to-pool exclusion.
- Tokenized beneficiary endpoint records.
- Endpoint support for:
  - bank account tokens
  - payment tokens
  - x402 wallets
  - internal ledgers
  - manual review
- Identity-verification boundaries.
- Tax-review boundaries.
- Employment-review boundaries.
- Settlement-instruction blocking states.
- Block reasons for:
  - unverified endpoints
  - unverified identities
  - unresolved tax review
  - unresolved employment review
  - disallowed currency
  - active holdback
  - missing approval
  - policy conflict
- Authorized settlement-target records.
- Explicit prohibition against agent payment execution.
- Reconciliation records.
- Settlement-receipt references.
- Royalty audit reports.
- Audit checks for:
  - evidence completeness
  - amount conservation
  - active-holdback exclusion
  - endpoint verification
  - compliance-boundary review
  - human approval
  - autonomous-execution prohibition
- Default settlement-handoff policy example.
- Passing settlement-handoff YAML example.
- Semantic validation for:
  - duplicate instruction identifiers
  - duplicate beneficiary instructions
  - source-plan consistency
  - holdback-ledger consistency
  - instruction amount conservation
  - released-holdback consistency
  - endpoint verification
  - identity verification
  - currency eligibility
  - tax-review completion
  - employment-review completion
  - raw-credential exclusion
  - settlement-batch conservation
  - instruction counts
  - reconciliation conservation
  - audit-state consistency
  - handoff authorization
  - execution prohibition
  - mandatory safety boundaries

### Changed

- Expanded `scripts/validate_examples.py` to support v0.1 through v0.5.
- Added a formal boundary between allocation approval and payment execution.
- Added protected endpoint references in place of raw payment credentials.
- Added post-handoff reconciliation support.
- Completed the first Royalty Audit layer.
- Completed the first specification arc from allocation evidence to settlement handoff.

### Scope

v0.5 prepares and audits settlement-handoff records.

It does not:

- create new rights
- change approved contribution weights
- resolve disputes autonomously
- include active holdbacks in settlement
- store raw bank or wallet credentials
- determine legal tax treatment autonomously
- bypass employment or identity review
- execute payment
- approve its own instructions

### Core Boundary

> The agent may prepare an audit-ready settlement handoff, but it must not execute payment, bypass compliance review, or approve its own instructions.

---

## [0.4.0-candidate] - 2026-07-18

### Added

- Dispute and Holdback Ledger specification.
- Explicit dispute-scope records.
- Full-allocation dispute support.
- Partial-allocation dispute support.
- Disputed and undisputed amount separation.
- Claimant records.
- Evidence-request records.
- Review deadlines.
- Partial-resolution records.
- Partial holdback releases.
- Continued-hold records.
- Return-to-pool records.
- Correction adjustments.
- Effective-holdback calculations.
- Release-event history.
- Human-authorized release receipts.
- Unaffected-allocation continuation controls.
- Holdback totals for:
  - source reserved amounts
  - correction adjustments
  - effective holdbacks
  - released amounts
  - currently held amounts
  - returned-to-pool amounts
- Default dispute and holdback policy example.
- Passing dispute-holdback YAML example.
- Semantic validation for:
  - duplicate dispute identifiers
  - duplicate holdback identifiers
  - source-allocation references
  - beneficiary-reference consistency
  - dispute-scope conservation
  - resolution conservation
  - holdback conservation
  - correction consistency
  - release-event totals
  - return-to-pool event totals
  - dispute-resolution consistency
  - dispute-state counts
  - affected-beneficiary counts
  - approval-state consistency
  - mandatory review controls
  - mandatory safety boundaries

### Changed

- Expanded the validation script to support v0.1 through v0.4.
- Added explicit separation between dispute resolution and payment execution.
- Added partial-processing support for unaffected allocations.
- Added a prohibition against unscoped global freezes.
- Added a prohibition against unauthorized redistribution of held amounts.

### Scope

v0.4 manages allocation disputes and holdbacks.

It does not:

- create new attribution
- determine final legal ownership
- resolve disputes autonomously
- release held amounts without human approval
- redistribute held amounts without verified resolution
- validate tax or employment obligations
- generate executable payment instructions
- execute payment

### Core Boundary

> Disputes must be scoped, unaffected amounts may proceed, and held amounts must not be redistributed without verified resolution and human approval.

---

## [0.3.0-candidate] - 2026-07-18

### Added

- Multi-Beneficiary Allocation Plan specification.
- Fixed-amount allocation support.
- Fixed-rate allocation support.
- Proportional-weight allocation support.
- Pooled-weight allocation support.
- Remainder-assignment support.
- Community-fund allocations.
- Platform-fee allocations.
- Minimum and maximum amount constraints.
- Constraint adjustments.
- Rounding-policy records.
- Remainder-policy records.
- Source-weight references.
- Payable-candidate allocation states.
- Reserved-for-review allocation states.
- Excluded allocation states.
- Reserve-reason records.
- Allocation-plan totals for:
  - fixed allocations
  - proportional pools
  - proportional allocations
  - final plan amounts
  - payable candidates
  - reserved amounts
  - unallocated amounts
  - rounding residuals
- Default multi-beneficiary allocation policy example.
- Passing multi-beneficiary allocation-plan YAML example.
- Semantic validation for:
  - duplicate beneficiary identifiers
  - source-weight consistency
  - held-weight preservation
  - raw amount calculations
  - fixed-rate calculations
  - proportional-weight calculations
  - rounding calculations
  - remainder adjustments
  - minimum and maximum constraints
  - final-amount conservation
  - allocation-mode totals
  - payable and reserved totals
  - proportional-weight normalization
  - policy and plan total consistency
  - approval-state consistency
  - mandatory safety boundaries

### Changed

- Expanded the validation script to support v0.1 through v0.3.
- Added a formal separation between contribution weights and monetary allocations.
- Added explicit preservation of held contribution shares.
- Added fixed allocations before proportional-pool distribution.
- Added explainable calculations for every beneficiary.

### Scope

v0.3 translates approved weights and policy rules into a provisional allocation plan.

It does not:

- create attribution
- create legal ownership
- change approved contribution weights
- redistribute held weights
- resolve disputes
- authorize settlement
- execute payment

### Core Boundary

> The allocation plan may calculate a reserved amount, but it must not silently redistribute that amount or treat it as payable.

---

## [0.2.0-candidate] - 2026-07-18

### Added

- Contribution Weight Resolution specification.
- Attribution-reference records.
- Contribution-component records.
- Raw contribution scores.
- Policy multipliers.
- Weighted component scores.
- Policy adjustment records.
- Adjusted contribution scores.
- Included resolution states.
- Held-for-review resolution states.
- Excluded resolution states.
- Hold and exclusion reasons.
- Normalized contribution weights.
- Normalization targets.
- Normalization residuals.
- Held-weight treatment policy.
- Default contribution-weight policy example.
- Passing contribution-weight-resolution YAML example.
- Semantic validation for:
  - duplicate beneficiary identifiers
  - attribution-reference membership
  - component-score calculations
  - policy-adjustment calculations
  - adjusted-score totals
  - normalization calculations
  - held-weight preservation
  - exclusion-state consistency
  - beneficiary-state counts
  - evidence references
  - approval-state consistency
  - mandatory safety boundaries

### Changed

- Expanded the validation script to support v0.1 and v0.2.
- Added a formal evidence-to-weight transformation layer.
- Added policy-controlled normalization.
- Added support for retaining held beneficiaries inside normalization.

### Scope

v0.2 resolves provisional contribution weights from verified attribution evidence.

It does not:

- determine legal ownership
- create attribution
- assign final monetary amounts
- resolve held claims
- authorize payment
- execute settlement

### Core Boundary

> Contribution weights may be calculated from verified evidence, but the weight-resolution layer must not create the rights it measures.

---

## [0.1.0-candidate] - 2026-07-18

### Added

- Initial Allocation Ledger Record specification.
- Royalty-pool records.
- Gross, distributable, and excluded pool amounts.
- Beneficiary allocation records.
- Gross allocation amounts.
- Payable amounts.
- Held amounts.
- Allocation status records.
- Hold reasons.
- Evidence references.
- Human approval records.
- Ledger status records.
- Safety-boundary controls.
- Passing allocation-ledger YAML example.
- Initial semantic validation for:
  - duplicate beneficiary identifiers
  - beneficiary amount conservation
  - allocation-status consistency
  - hold-reason consistency
  - ledger total conservation
  - royalty-pool conservation
  - evidence-reference membership
  - approval-state consistency
  - mandatory safety boundaries

### Scope

v0.1 records an evidence-supported allocation state.

It does not:

- resolve contribution weights
- create legal ownership
- create new beneficiary rights
- resolve disputes
- generate payment instructions
- execute payment

### Core Boundary

> The ledger records supported allocation amounts, but it does not create rights or execute transfers.

---

## First Arc

The v0.1–v0.5 candidate sequence establishes the following record chain:

```text
Allocation Ledger Record
        ↓
Contribution Weight Resolution
        ↓
Multi-Beneficiary Allocation Plan
        ↓
Dispute and Holdback Ledger
        ↓
Settlement Handoff and Royalty Audit
```

The completed first arc provides:

- evidence-backed allocation records
- explainable contribution weighting
- multi-beneficiary amount planning
- scoped dispute and holdback processing
- non-executable settlement handoffs
- royalty-audit and reconciliation boundaries
- explicit human approval
- explicit prohibition against autonomous payment
