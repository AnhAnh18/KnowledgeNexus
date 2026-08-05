# M9-B Re-review Fix Plan 15

Address only `38-review-17.md`:

- Revalidate every `authority_observations` entry with
  `GitFileObservation.__post_init__` and compare each provenance field
  explicitly (path, raw bytes/sizes, normalized text/size, authority flag),
  avoiding custom equality semantics.
- Add a forged-authority-equality adversarial test and rerun all validation plus
  a fresh independent review.
