# W5-C - controlled second-sync sparse delta packet

Main-machine operator packet. Execute only after the owner has inspected and
accepted the sanitized W5-B packet and grants a new authorization. This packet
must bind to the accepted W5-B base dataset version without exposing it in
chat or Git.

## Required safe scenario

The owner or authorized administrator must attest a safe, reversible scenario
containing, where available, one content change, one approved 404 case, one
403 access-revoked case, one moved-out-of-scope case, and one ACL-only change.
If any case cannot be established safely, stop and return a pending gate. Never
edit or delete Confluence content from this runbook and never fabricate a
disposition.

Credentials remain only in the live process environment and are cleared before
offline delta export. Never return credentials or raw runtime artifacts.

## Authorized sequence

```powershell
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase inventory <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase capture-pages <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase process-pages <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase capture-drawio <approved-options>
python -m knowledgenexus.foundation.cli.confluence_subtree_corpus --phase capture-delta-inventory <approved-options>
python -m knowledgenexus.foundation.cli.export_m10_snapshot `
  --export-mode delta --base-dataset-version <accepted-base-version> <approved-offline-options>
```

Complete inventory must precede missing-page probes. Preserve status/body
evidence before checkpointing `delta-inventory.json`. Offline delta export
must run with sockets forbidden and must perform zero GETs.

## Required assertions

Verify sparse rows/tombstones, strict base-overlay readback, exact 404 detail,
403 access revocation, 401/retry failure, in-scope missing inconsistency,
chunk/media/relation/ACL cascade, ACL-only behavior, unchanged empty delta,
deterministic repeat, and unchanged base/raw/state inputs. Return aggregate
results only using `W5_C_SANITIZED_EVIDENCE_TEMPLATE.json`.
