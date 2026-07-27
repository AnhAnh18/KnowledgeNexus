# Hybrid Retrieval with RRF

Hybrid retrieval means running **dense** and **sparse** search, then merging ranks.

## Reciprocal Rank Fusion (RRF)

For each candidate id:

`score = sum(1 / (k + rank_i))` across ranked lists, typically `k = 60`.

## When hybrid helps

- Exact class names: `ChunkStorageService`
- Error codes: `ERR_AUTH_401`
- Model names: `BGE-M3`

Dense alone often paraphrases well but can miss rare tokens. Sparse / lexical weights
recover those tokens. Always A/B with eval (`kn-eval`) before making hybrid the default.
