# W5-B - Root-1 controlled full snapshot packet

Main-machine operator packet. Execute only after a distinct owner
authorization naming this one live sequence. Replace angle-bracket values on
the main machine only; never commit or transmit them.

## Required controls

- Freeze and record the approved execution head; require a clean tracked tree.
- Use fresh absent output roots with plain existing parents; reject symlink or
  reparse components and insufficient free disk.
- Keep credentials in the live process environment only and clear them before
  offline processing/export.
- Use the active reliability profile and explicit BGE-M3 tokenizer directory.
- Text plus Draw.io only. Set media policy to `required` only for Draw.io
  references; do not enable generic PDF/image/OCR paths.
- No automatic operator retry. Preserve valid raw/checkpoint artifacts after
  failure and report aggregate counters only.

## Authorized sequence

Run the existing phases in order. The exact CLI signatures are discovered from
`--help` on the frozen head; do not invent historical flags.

```powershell
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase inventory <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase capture-pages <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase process-pages <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase capture-drawio <approved-options>
python -m knowledgenexus.foundation.cli.export_m10_snapshot `
  --export-mode full_snapshot <approved-offline-options>
```

Exercise one controlled stop after committed batches, then resume the same run
and prove committed windows/pages were not fetched again. Do not start a second
live sequence after the authorized sequence completes.

Publish the preserved generation twice into separate fresh dataset roots with
the same semantic inputs and `generated_at`. Verify privately that version
directories, dataset version, digest, eight streams, strict readback, counts,
cross-stream closure, `LATEST.txt`, and raw/state inputs are byte-identical.

## Sanitized return packet

Return only the aggregate fields in `W5_B_SANITIZED_EVIDENCE_TEMPLATE.json`.
Do not return IDs, URLs, hostnames, paths, titles, raw logs, credentials, or
full hashes. Include `authorization_consumed` even when the run fails after its
first live invocation.
