# Eval leaderboard (2-layer)

L1 = oracle `search_query` → retrieve.  
L2 = Skill-like `plan(user_question)` → retrieve.  
Gap = L1 − L2 (Skill/query formulation loss).

| When | Label | L1 Hit@10 | L2 Hit@10 | Gap@10 | L1 MRR | L2 MRR | N |
|------|-------|-----------|-----------|--------|--------|--------|---|
| 2026-07-28T09:49:55 | dense-baseline | 1.000 | — | — | 0.929 | — | 50 |
| 2026-07-28T11:28:37 | hybrid-rrf | 1.000 | — | — | 0.930 | — | 50 |
| 2026-07-29T01:21:32 | dense-baseline | 0.985 | — | — | 0.817 | — | 65 |
| 2026-07-29T01:28:06 | hybrid-rrf | 1.000 | — | — | 0.823 | — | 65 |

## Latest vs previous

- L1 Hit@10: 1.000 (+0.015)
- L2 Hit@10: —
- Gap@10: —
- Labels: `dense-baseline` → `hybrid-rrf`

## A/B Comparison (latest dense vs hybrid)

**Run 1:** `dense-baseline` — 2026-07-29T01:21:32  
**Run 2:** `hybrid-rrf` — 2026-07-29T01:28:06

| Metric | Dense | Hybrid | Delta |
|--------|-------|--------|-------|
| L1 Hit@5 | 0.969 | 0.985 (+0.015) | |
| L1 Hit@10 | 0.985 | 1.000 (+0.015) | |
| L1 MRR | 0.817 | 0.823 (+0.006) | |
| L2 Hit@5 | — | — | |
| L2 Hit@10 | — | — | |
| L2 MRR | — | — | |

**Per-case:** 8 improved, 2 regressed, 65 total
- Improved: ex-024, hyb-005, hyb-008, hyb-010, hyb-012, hyb-013, mix-006, mix-007
- Regressed: ex-025, sem-006

## Decision

➖ **No significant change** — L1 Hit@10 roughly equal. Check per-case for tag-specific improvements.
