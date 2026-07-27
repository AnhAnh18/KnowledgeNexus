# FlagEmbedding Install Notes

Local dense embedding depends on the optional extra:

```bash
uv sync --extra embedding
```

That installs **FlagEmbedding** (and torch). Without it, `BgeM3Embedder` raises ImportError.

Set `EMBEDDING_MODEL_PATH` when using a local snapshot of **BAAI/bge-m3** instead of downloading at runtime.
