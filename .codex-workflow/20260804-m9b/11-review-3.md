# M9-B Independent Re-review (fix implementation)

Scope: revised plan, fix artifact, and M9-B production/tests only. No source files were edited.

## Findings

### P1 - `CodeDocumentPlan` accepts forged observation provenance and authority

`CodeDocumentPlan.__post_init__` derives document hashes and metadata from the supplied `GitFileObservation`, but neither `GitFileObservation` nor the plan verifies that `normalized_text` is the canonical normalization of `raw_bytes`, or that `symbol_authority` matches the fixed C++/Java suffix map. A direct model-boundary caller can therefore construct a successful plan whose document hash/size fields agree with an observation containing unrelated raw bytes, or mark `README.md` as symbol-authoritative. Reproduction: start from a valid plan, replace `README.md` observation raw bytes with `b"X"` (and its raw size/metadata), and the plan is accepted; separately flip `README.md` authority to `True`, update its metadata/authority tuple, remove its fallback chunk, and the plan is accepted. The affected checks are `git_code_source.py:247-275` and `git_code_source.py:415-507`.

### P1 - `CodeDocumentPlan` accepts impossible fallback line ranges

The direct plan validator checks only positive ordering (`line_start <= line_end`) and part counters. It never bounds ranges to the observation's source line count or otherwise enforces the fallback contract's one-based source-line semantics. Reproduction: take a valid fallback chunk and change `line_start`/`line_end` to `999`/`1000`; `CodeDocumentPlan` accepts the forged chunk unchanged. This violates the required impossible line-counter rejection at `git_code_source.py:547-561` and lets downstream consumers receive a chunk that cannot refer to its source document.

### P2 - `GitScanMetrics` accepts inconsistent excluded-byte counters

`GitScanMetrics` validates the exclusion counts' arithmetic but does not reject `excluded_bytes > 0` when all exclusion counters are zero. A direct plan/result boundary can therefore publish metrics claiming excluded bytes with no excluded files (for example `seen=2, included=2, excluded_generated=excluded_vendor=excluded_binary=0, excluded_bytes=1`), and `CodeDocumentPlan` does not add a cross-check. This violates the required typed metrics cross-field consistency at `git_code_source.py:282-307` and `git_code_source.py:363-415`.

## Validation

- `python -m pytest -q tests/foundation/domain/models/test_git_code_source.py tests/foundation/infrastructure/git/test_local_git_repository_reader.py tests/foundation/application/use_cases/test_build_git_code_documents.py tests/architecture/test_m9b_git_boundary.py --basetemp=.pytest-m9b-review3` -> `28 passed`.
- Direct forged-plan probes reproduced all three findings: mismatched raw/normalized observation accepted, non-authority `README.md` marked authority accepted, forged `999/1000` line range accepted, and nonzero excluded bytes with zero exclusion counts accepted.

VERDICT: FAIL
