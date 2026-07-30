# Local Provenance Mapping

Copy this file to `.local_ai/LOCAL_PROVENANCE.md` in each repository. The
populated file is intentionally ignored because commit identities differ across
independent histories.

## Current task

```text
TASK_ID=<milestone/task identifier>
REPOSITORY_ROLE=<working-review|main-machine>
SOURCE_REVIEW_BASE=<local commit or n/a>
SOURCE_REVIEW_HEAD=<local commit or n/a>
TRANSFER_METHOD=<patch|exact-content|native implementation>
TRANSFERRED_FILE_SET=<local manifest reference>
TREE_EQUIVALENCE=<PASS|FAIL|NOT_REQUIRED>
MAIN_TRANSFER_HEAD=<local commit or n/a>
MAIN_EXECUTION_HEAD=<local commit or n/a>
REVIEW_VERDICT=<APPROVE|REQUEST_CHANGES|PENDING>
ACCEPTANCE_GATE=<PASS|FAIL|PENDING|NOT_REQUIRED>
```

Do not copy populated SHA values into `IMPLEMENTATION_STATE.md`, `ROADMAP.md`,
or portable review summaries.
