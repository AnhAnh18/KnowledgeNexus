# Repository Transfer Policy

Status: local workflow policy for this KnowledgeNexus working/review repository.
Do not assume that another repository shares this Git history.

## Durable milestone-first state

Cross-repository durable documentation is milestone-based, not commit-based.
The authoritative portable identity is the task or acceptance gate, for
example:

```text
M6G-D-O1: COMPLETE AND APPROVED
M6G-D-R3: ACCEPTANCE PASS
M6G-D3: DOCUMENTATION CLOSEOUT COMPLETE
M7: NEXT AND UNBLOCKED
```

`IMPLEMENTATION_STATE.md`, `ROADMAP.md`, and portable review summaries record:

```text
milestone or task ID
status and review verdict
verification and acceptance gates
transferred file set or artifact kind
next and blocked tasks
```

They must remain correct when copied into an independent repository that has
different commit history. A foreign commit SHA must never be a completion gate,
checkout requirement, or prerequisite for understanding current state.

Commit mappings are local execution metadata. Store them only in the ignored
`.local_ai/LOCAL_PROVENANCE.md`, using
`.local_ai/LOCAL_PROVENANCE.example.md` as the format. Do not transfer or commit
the populated local file.

## Repository roles

### Working/review repository

The repository used by Codex, an implementer, or an independent reviewer.
Commits here establish source-review provenance only.

Use:

```text
SOURCE_REVIEW_BASE
SOURCE_REVIEW_HEAD
```

These SHAs identify commits in this repository's history. They are used in
local review commands and `LOCAL_PROVENANCE.md`; they must not be used as
mandatory checkout targets or durable milestone identities.

### Main-machine repository

The independent repository on the primary machine that retains external raw
artifacts/sidecars and runs controlled acceptance.

Use:

```text
MAIN_TRANSFER_HEAD
MAIN_EXECUTION_HEAD
```

`MAIN_TRANSFER_HEAD` is the local commit created after applying the approved
transferred changes. `MAIN_EXECUTION_HEAD` is the exact local commit used for
an acceptance run. They may be the same commit, but that must be stated rather
than assumed.

## Locked rules

- Never require the main-machine repository to check out, fast-forward to, or
  otherwise possess a `SOURCE_REVIEW_HEAD`.
- Never claim two independent repositories should have the same commit SHA.
  Commit identity depends on the complete commit object and parent history.
- Transfer approved changes through an explicit reviewed patch set or another
  owner-approved exact-content mechanism.
- Apply transferred changes in the main-machine repository, verify them, then
  create a new local transfer commit. Its SHA becomes `MAIN_TRANSFER_HEAD`.
- Before controlled acceptance, require a clean tracked worktree and record the
  exact `MAIN_EXECUTION_HEAD`.
- If an acceptance run necessarily starts with a known tracked deviation,
  record the before/after tracked diff and obtain an explicit deviation
  verdict; never silently call that state clean.
- Record source-review and main-machine provenance separately in runtime
  prompts, runbooks, and the ignored local provenance file. Portable summaries
  record the milestone and equivalence verdict, not the local SHAs.
- A source-review approval does not approve unrelated local changes present in
  the main-machine repository.

## Tree-equivalence proof

Tree equivalence is scoped to the exact transferred file set:

```text
approved production files
approved active contracts
approved tests
approved operator/runbook files when included in the transfer
```

Do not require whole-repository tree equality. The repositories may
legitimately differ in:

```text
.local_ai state and review notes
raw artifacts and sidecars
patch-transfer files
local configuration
unrelated parent history
```

Equivalence must be demonstrated from exact file content or Git tree/blob
identities for the transferred set. Similar filenames, commit messages, test
counts, or short SHAs are not proof.

Record the portable result:

```text
TASK_ID=<milestone/task identifier>
TRANSFER_METHOD=<approved patch or exact-content mechanism>
TRANSFERRED_FILE_SET=<explicit manifest>
TREE_EQUIVALENCE=PASS
EXECUTION_GATE=PASS
```

Record the repository-local mapping only in `LOCAL_PROVENANCE.md`:

```text
SOURCE_REVIEW_BASE=<working/review repository commit>
SOURCE_REVIEW_HEAD=<approved working/review repository commit>
TRANSFER_METHOD=<approved patch or exact-content mechanism>
TRANSFERRED_FILE_SET=<explicit manifest>
TREE_EQUIVALENCE=PASS
MAIN_TRANSFER_HEAD=<main-machine local commit>
MAIN_EXECUTION_HEAD=<main-machine commit used for acceptance>
```

## Task workflow

```text
working/review repository
    source implementation
    -> independent review
    -> approved SOURCE_REVIEW_HEAD
    -> approved transfer artifact

main-machine repository
    apply approved transfer
    -> verify transferred-file equivalence
    -> create MAIN_TRANSFER_HEAD
    -> freeze MAIN_EXECUTION_HEAD
    -> run controlled acceptance
```

Documentation closeouts created in the working/review repository remain source
documentation provenance. If they are required on the main-machine repository,
transfer their exact approved changes and create a separate local
documentation-only commit there. Portable closeout text must identify the
milestone and gates without requiring either local commit SHA.

## Prompt requirement

Every live cross-repository implementation, review, or acceptance prompt that
uses a SHA must name its repository role. Avoid ambiguous labels such as only
`BASE`, `HEAD`, or `production head`. After the session, keep those mappings in
the ignored local provenance file; durable shared documents use task IDs and
gate results.
