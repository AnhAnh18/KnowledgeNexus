# Eval leaderboard (2-layer)

L1 = oracle `search_query` → retrieve.  
L2 = Skill-like `plan(user_question)` → retrieve.  
Gap = L1 − L2 (Skill/query formulation loss).

| When | Label | L1 Hit@10 | L2 Hit@10 | Gap@10 | L1 MRR | L2 MRR | N |
|------|-------|-----------|-----------|--------|--------|--------|---|
| 2026-07-28T09:49:55 | dense-baseline | 1.000 | — | — | 0.929 | — | 50 |

## Latest vs previous

- L1 Hit@10: 1.000 (+0.000)
- L2 Hit@10: —
- Gap@10: —
- Labels: `dense-baseline`
