# M7-C5 Inventory Acceptance Consolidation

Sanitized aggregate evidence only. No raw/runtime artifact, endpoint,
credential, identity, content, path, or hash is retained here.

## Gate Results

| Gate | Result | Evidence |
| --- | --- | --- |
| M7-C5-RESERVE-ORDER | PASS | 4 synthetic attempts; durable reservation precedes every request; retry/pacing sleeps are deterministic. |
| M7-C5-RESERVE-CRASH | PASS | Reservation-before-I/O interruption consumes one unit; resume completes without refund. |
| M7-C5-RESPONSE-CRASH | PASS | Post-response interruption resumes to the uninterrupted window, occurrence, and transition state. |
| M7-C5-TXN-ROLLBACK | PASS | Before-transaction and after-row/before-cursor faults leave zero partial window rows and preserve the cursor. |
| M7-C5-ACK-REPLAY | PASS | Post-commit acknowledgement interruption replays without a duplicate transition. |
| M7-C5-BUDGET | PASS | Denied budget emits no request and no retry sleep; cap-plus-one denial is fail-closed. |
| M7-C5-IDENTITY | PASS | Exact root/page IDs, uniqueness, cross-root duplicate occurrence semantics, and excluded-page budget accounting are asserted. |
| M7-C5-10K | PASS (baseline) | One fresh isolated run validated 10,000 pages; 200 windows; 201 requests/reservations; 202 transitions; bounded window size 50; deterministic result. Later local reruns hit a checkpoint-failure and are not used to broaden the baseline claim. |
| M7-C5-100K | INCOMPLETE | Child-process measurement methodology remains available; no absolute RSS threshold or 100,000-page completion claim is made. |
| M7-D5 | PAUSED | Raw/checkpoint linkage representation and schema-v1 compatibility remain a separate owner-decision boundary. |

## Validation

- Focused consolidation: `11 passed, 1 skipped`.
- M7-C/M7-B regression: `235 passed, 15 skipped`.
- Tracked 10k opt-in gate: one fresh isolated run `1 passed`; later local reruns were not accepted as new gate evidence after checkpoint-failure.
- Compile and whitespace checks: passed.
