RECOMMENDED_IMPLEMENTATION_PROFILE: complex

# M10-C Fix Plan Review

Verdict: PASS with bounded scope.

The remediation must address all three confirmed findings without changing
the legacy one-page path or any writer, publisher, CLI, network, roadmap, or
state behavior:

- Use a dedicated strict profile-identifier validator for the three generic
  profile fields. It must accept the approved alphanumeric/underscore/dot/
  hyphen values but reject path separators, URL schemes, whitespace, control
  characters, and arbitrary report text before rendering.
- Check `type(staging_path) is Path` at the generic `complete` boundary before
  invoking any path method. Return the existing sanitized generic error and
  leave the legacy branch unchanged.
- Treat blank JSONL lines as malformed in strict generic parsing; preserve
  duplicate-key and non-finite-number rejection.

Acceptance requires adversarial tests for Windows/Unix paths, HTTP(S) URLs,
wrong path-like objects with side effects, `object()`/`None`, blank lines,
and all existing deterministic/no-clobber/sanitization cases. Run focused
M10-C, M6G exporter/writer/publisher/one-page regression, architecture,
compileall, and diff-check, then a fresh independent review.
