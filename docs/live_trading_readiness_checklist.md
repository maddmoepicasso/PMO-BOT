# PMO Bot - Live Trading Readiness Checklist

Status as of: June 19, 2026

Purpose: single source of truth for what must be true before live trading is unlocked.
This checklist is updated as gates are met. It is not code, not an automatic trigger,
and does not unlock or arm live trading.

## Hard Gates

All hard gates must be true before live trading is reviewed for unlock.

| # | Gate | Threshold | Current | Status |
|---|------|-----------|---------|--------|
| 1 | Clean closed trades collected | >= 150-200 | 70/200 | NOT MET |
| 2 | Win rate, raw full equity track | >= 52% | 46.0% | NOT MET |
| 3 | Profit factor, raw full equity track | >= 1.25 | 0.996-1.00 | NOT MET |
| 4 | Score model rebuilt on confirmed band data | Complete | Pending 150+ trades | NOT MET |
| 5 | Journal/broker reconciliation | Clean, no orphans | 0 orphans, root cause fixed | MET |
| 6 | Closed-trade duplication check | No duplicate closed outcomes | `closed_duplicate_pairs: {}` | MET |
| 7 | `PAPER_PROOF_QUALITY_BREAKER` | PF >= 0.80 to even submit paper trades | Active | MET, gate functioning |
| 8 | Explicit owner/admin sign-off | Manual review, separate from metrics | Not yet performed | NOT MET |

Current hard-gate status: 3 of 8 met. Live remains correctly locked.

## Why Raw Metrics Lag Clean Metrics

The raw 46.0% WR / PF about 1.00 is dragged down by:

- 30 blocked-symbol trades at 6.7% WR and PF 0.234. Already addressed via blocklist:
  HOOD, PSQ, RWM, CVX.
- Early opening-window trades before the 09:40 gate, which ran at 34.7% WR.
  Already addressed via the hard opening gate.

Clean ex-block trades currently show 66.7% WR and PF 3.348. This is promising,
but it is a post-hoc filtered subset, not yet proof that the system as currently
configured will perform the same way prospectively on new, unseen trades.

Gates 1-4 convert "this filtered subset looked good" into "this system, run forward
with no after-the-fact filtering, meets the bar."

## Score Band Evidence

Supporting case for rebuild, not yet sufficient for live.

Clean trades only:

| Band | Trades | WR | PF |
|------|--------|----|----|
| 65-74 | 30 | 76.7% | 9.931 |
| 75-77 | 18 | 55.6% | 1.894 |
| 78-84 | 8 | 50.0% | 1.110 |

The signal is consistent and statistically meaningful at the current sample size,
but 8-30 trades per band is still thin for a model rebuild. Target before rebuild:
150+ total clean trades, ideally 40+ per relevant band.

## Soft Readiness Factors

These are not hard gates, but they inform owner judgment.

- [ ] Crypto paper track stability over more sessions. Current state: 15W/0L,
  strong but small N.
- [ ] At least one full normal trading week completed post-fixes:
  5 days, no holidays, no FOMC.
- [ ] Regime/CFR confirmation behaving as expected across multiple regime transitions.
- [ ] Repeated-lifecycle-write bug confirmed fully resolved over sustained runtime,
  not just one day post-fix.
- [ ] Watchlist expansion audited for noise vs. signal contribution.

## Future Live Shape

This is intentionally not decided yet. These are future owner-review questions,
not defaults:

- Position sizing for first live trades. Recommendation: smallest viable size,
  not full sizing.
- Which asset class goes live first: equity vs. crypto. Crypto has stronger
  current evidence but remains small N.
- Whether live starts with rebuilt v3 score model or the current model with
  corrected gates.
- Rollback criteria: what triggers re-locking live trading after unlock.

## Review Cadence

Revisit this checklist:

- At 100 clean trades collected.
- At 150 clean trades collected.
- At 200 clean trades collected.
- After any data integrity issue is discovered.

## Enforcement Note

This document does not unlock anything. It is a reference checklist for owner
decision-making only.

No gate listed here is enforced by this file. Actual enforcement remains in PMO's
code-level safety locks, including `PAPER_PROOF_QUALITY_BREAKER`, live lock, and
admin gates.
