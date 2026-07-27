# CHUNKING_SPEC Medium Profile

Foundation chunking follows **CHUNKING_SPEC** with `chunker_version` **1.2.0**.

## Active medium budget (provisional)

- target_tokens: 450
- minimum_tokens: 96
- hard_maximum_tokens: 1000
- overlap_tokens: 64

Tokenizer identity is BGE-M3 / SentencePiece. Changing semantic split rules requires a
chunker_version bump and full snapshot invalidation.
