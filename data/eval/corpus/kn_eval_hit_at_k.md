# kn-eval Hit@k Runner

**kn-eval** scores retrieval against golden JSONL.

## Layers

- Layer 1: oracle `search_query` → Hit@k / MRR
- Layer 2: Skill-like `plan(user_question)` → Gap = L1 − L2

Labels such as `dense-before-hybrid` and `hybrid-rrf` are written into
`data/eval/results/LEADERBOARD.md` for A/B comparison.
