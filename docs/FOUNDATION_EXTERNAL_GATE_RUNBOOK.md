# Foundation External Gate Runbook

This runbook records the only external evidence still required before the
Foundation goal can be marked complete. Keep all page content, credentials,
raw captures, and runtime artifacts outside Git.

## F4 M8/M9

1. Run the bounded 10-20 page M8 corpus with the exact pinned tokenizer bundle
   (`tokenizer.json`, SHA-256 from the active chunking profile). The repository
   CLI is:
   `PYTHONPATH=src python -m knowledgenexus.foundation.cli.accept_confluence_mini_corpus --data-root <external-data-root> --run-id <run-id> --generation-id <generation-id> --selection-path <external-selection.json> --profile-path <profile.json> --tokenizer-assets-dir <external-tokenizer-dir>`.
   Keep every supplied path outside Git and outside `.local_ai`.
2. Run the five media kinds: `drawio`, `digital_pdf`, `image_only_pdf`,
   `image`, and `chart_screenshot`.
3. Convert processor results to
   `SanitizedMediaProcessorOutcome`/`SanitizedMediaProcessorRun` and evaluate
   with `EvaluateBoundedMediaCorpusAcceptance`.
4. OCR may be marked `approved` only with a sanitized real-capture digest,
   offline runtime identity, model/build identity, and bounded limits.
   Validate the sanitized approval envelope with:
   `PYTHONPATH=src python -m knowledgenexus.foundation.cli.evaluate_foundation_gates --gate ocr --input <ocr-approval.json>`.
   For the media gate, set `real_capture_attested: true` and
   `transport: "production"`; otherwise a `sanitized_real_capture` envelope
   remains `pending_external_input` even when its digests repeat.
   A sanitized gate envelope can be evaluated with:
   `PYTHONPATH=src python -m knowledgenexus.foundation.cli.evaluate_foundation_gates --gate media --input <sanitized-media-gate.json>`.

## F5/F7

1. Publish two identical bounded M10 runs and retain only sanitized readback
   metadata: dataset version, digest, stream counts, closure booleans, RSS,
   duration, and transport kind. `export_m10_snapshot` is an injected boundary:
   the production harness must construct `ConfluenceM10Adapter`/
   `GitM10Adapter` over approved source ports, then call
   `M10FullSnapshotExporter.execute(request)` twice.
2. Evaluate with `EvaluateScaleGateEvidence` for the applicable 10k/100k
   target, or use the sanitized CLI:
   `PYTHONPATH=src python -m knowledgenexus.foundation.cli.evaluate_foundation_gates --gate scale --input <sanitized-scale-gate.json>`.
3. A synthetic fixture is useful for development but does not satisfy the
   real-input exit gate; production evidence must use `sanitized_real_capture`.

The evaluator rejects malformed types, duplicate identities, missing stream
counts, impossible counters, nondeterministic repeats, and failed closure
checks before producing a gate record.
