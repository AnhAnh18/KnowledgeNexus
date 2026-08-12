# M9-A3 Independent Review

## Initial findings

- `P1`: application dispatch accepted a result whose extraction-detail
  processor kind did not match the routed MIME kind.
- `P1`: application dispatch did not bind `content_hash`/`raw_uri` to the
  materialized envelope body.
- `P2`: draw.io `byte_count` reported canonical output bytes instead of raw
  input bytes.
- `P2`: PDF/OCR capability cardinality and page/image counters lacked explicit
  upper bounds; output limits were checked after intermediate accumulation.
- `P2`: the reviewed plan required an architecture guard for no engine,
  network, or file side effects.

## Resolution

All findings were fixed in the bounded M9-A3 implementation. A focused
re-review was run in an independent session after the fixes.
