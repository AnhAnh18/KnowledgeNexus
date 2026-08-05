"""Pinned, read-only local Git repository reader."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from knowledgenexus.foundation.domain.models.git_code_source import (
    GitCodeBuildError,
    GitCodeBuildFailureCategory,
    GitFileObservation,
    GitRepositorySnapshot,
    GitScanMetrics,
    GitSourceConfig,
)
from knowledgenexus.foundation.domain.rules.text_normalization import (
    TextNormalizationRules,
)


_STDOUT_CAP = 32 * 1024 * 1024
_STDERR_CAP = 64 * 1024
_TIMEOUT_SECONDS = 10.0
_GENERATED = frozenset({"generated", "gen", "build", "dist", "out", "target", "node_modules"})
_VENDOR = frozenset({"vendor", "third_party", "external", "pods"})
_BINARY_EXTENSIONS = frozenset(
    {
        ".7z",
        ".a",
        ".apk",
        ".avi",
        ".bin",
        ".bmp",
        ".class",
        ".dll",
        ".dylib",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lib",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".otf",
        ".pdf",
        ".png",
        ".so",
        ".tar",
        ".ttf",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".xz",
        ".zip",
    }
)
_AUTHORITY_EXTENSIONS = frozenset(
    {".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".inl", ".java"}
)
_LANGUAGE_BY_EXTENSION = {
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".inl": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".php": "php",
    ".py": "python",
    ".pyw": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".mk": "make",
    ".make": "make",
    ".gradle": "gradle",
    ".sql": "sql",
    ".xml": "xml",
    ".xsd": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    ".svg": "xml",
}
_SHA1 = set("0123456789abcdef")


@dataclass(frozen=True)
class GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes

    def __post_init__(self) -> None:
        if type(self.returncode) is not int:
            raise TypeError("returncode is invalid")
        if type(self.stdout) is not bytes or type(self.stderr) is not bytes:
            raise TypeError("command output is invalid")


class GitCommandRunner(Protocol):
    def run(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path,
        stdin: bytes | None,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> GitCommandResult: ...


class SubprocessGitCommandRunner:
    """Execute a fixed local Git argv with prompts/config/network seams closed."""

    def __init__(self, *, git_executable: str | Path | None = None) -> None:
        executable = str(git_executable) if git_executable is not None else shutil.which("git")
        if not executable or not Path(executable).is_absolute():
            raise ValueError("git executable is invalid")
        self._git_executable = executable

    def run(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path,
        stdin: bytes | None,
        timeout_seconds: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
    ) -> GitCommandResult:
        if type(argv) is not tuple or any(type(item) is not str or not item for item in argv):
            raise ValueError("argv is invalid")
        if not _allowed_argv(argv):
            raise ValueError("argv is not an allowed read-only Git command")
        if not isinstance(cwd, Path) or not cwd.is_absolute():
            raise ValueError("cwd is invalid")
        if stdin is not None and type(stdin) is not bytes:
            raise TypeError("stdin is invalid")
        if type(timeout_seconds) is not float or timeout_seconds <= 0 or timeout_seconds > 10:
            raise ValueError("timeout is invalid")
        if type(max_stdout_bytes) is not int or max_stdout_bytes < 1 or max_stdout_bytes > _STDOUT_CAP:
            raise ValueError("stdout cap is invalid")
        if type(max_stderr_bytes) is not int or max_stderr_bytes < 1 or max_stderr_bytes > _STDERR_CAP:
            raise ValueError("stderr cap is invalid")
        env = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "PATH": os.environ.get("PATH", ""),
        }
        for name in ("SystemRoot", "WINDIR", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
        try:
            process = subprocess.Popen(
                [self._git_executable, *argv],
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                shell=False,
            )
        except (OSError, ValueError) as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED) from exc
        stdout_box: list[object] = [b"", False]
        stderr_box: list[object] = [b"", False]
        stdout_thread = threading.Thread(
            target=_drain_stream, args=(process.stdout, max_stdout_bytes, stdout_box), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_drain_stream, args=(process.stderr, max_stderr_bytes, stderr_box), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            if process.stdin is not None:
                if stdin:
                    process.stdin.write(stdin)
                    process.stdin.flush()
                process.stdin.close()
            returncode = process.wait(timeout=timeout_seconds)
        except (BrokenPipeError, OSError):
            process.kill()
            process.wait()
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED) from exc
        finally:
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
        if bool(stdout_box[1]) or bool(stderr_box[1]):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        return GitCommandResult(returncode, bytes(stdout_box[0]), bytes(stderr_box[0]))


def _drain_stream(stream: object, cap: int, result_box: list[object]) -> None:
    if stream is None or not hasattr(stream, "read"):
        result_box[1] = True
        return
    collected = bytearray()
    overflow = False
    while True:
        block = stream.read(64 * 1024)  # type: ignore[union-attr]
        if not block:
            break
        if len(collected) < cap:
            collected.extend(block[: cap - len(collected) + 1])
        if len(collected) > cap:
            overflow = True
            del collected[cap:]
    result_box[0] = bytes(collected)
    result_box[1] = overflow


class LocalGitRepositoryReader:
    def __init__(self, *, runner: GitCommandRunner | None = None) -> None:
        if runner is None:
            self._runner = SubprocessGitCommandRunner()
            return
        run = getattr(runner, "run", None)
        if not callable(run):
            raise TypeError("runner is invalid")
        self._runner = runner

    def read(self, *, config: GitSourceConfig) -> GitRepositorySnapshot:
        if type(config) is not GitSourceConfig:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        try:
            GitSourceConfig.__post_init__(config)
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST) from exc
        root = self._validate_root(config.clone_root)
        self._verify_identity(root, config)
        entries = self._read_tree(root, config)
        if len(entries) > config.budgets.max_tree_entries:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)

        sizes = self._read_blob_sizes(root, config, entries)
        observations: list[GitFileObservation] = []
        excluded_generated = excluded_vendor = excluded_binary = excluded_bytes = 0
        candidate_entries: list[tuple[str, str, int]] = []
        for mode, object_id, path in entries:
            size = sizes.get(object_id)
            if size is None:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            if size > config.budgets.max_file_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
            category = _exclusion_category(path)
            if category == "generated":
                excluded_generated += 1
                excluded_bytes += size
                continue
            if category == "vendor":
                excluded_vendor += 1
                excluded_bytes += size
                continue
            if _is_binary_extension(path):
                excluded_binary += 1
                excluded_bytes += size
                continue
            candidate_entries.append((object_id, path, size))

        if len(candidate_entries) > config.budgets.max_files:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        raw_total = sum(sizes[object_id] for _, object_id, _ in entries)
        if raw_total > config.budgets.max_total_raw_bytes:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        candidate_body_request_size = sum(size for _, _, size in candidate_entries)
        if candidate_body_request_size + len(candidate_entries) > _STDOUT_CAP:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        blobs = self._read_blobs(root, config, candidate_entries)
        for object_id, path, size in candidate_entries:
            raw = blobs.get(object_id)
            if raw is None or len(raw) != size:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            if b"\x00" in raw:
                excluded_binary += 1
                excluded_bytes += size
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_UTF8) from exc
            if any(
                (ord(char) < 0x20 and char not in "\t\r\n")
                or 0x7F <= ord(char) <= 0x9F
                for char in text
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.UNSUPPORTED_TEXT_CONTROL)
            normalized = TextNormalizationRules.normalize_text(text)
            normalized_size = len(normalized.encode("utf-8"))
            if normalized_size > config.budgets.max_normalized_bytes:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
            authority = _is_symbol_authority(path)
            observations.append(
                GitFileObservation(
                    path=path,
                    raw_bytes=raw,
                    raw_byte_size=size,
                    normalized_text=normalized,
                    normalized_byte_size=normalized_size,
                    symbol_authority=authority,
                )
            )
        observations.sort(key=lambda item: item.path)
        owned_bytes = sum(
            item.raw_byte_size + item.normalized_byte_size for item in observations
        )
        if owned_bytes > config.budgets.max_in_memory_bytes:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        metrics = GitScanMetrics(
            seen=len(entries),
            included=len(observations),
            excluded_generated=excluded_generated,
            excluded_vendor=excluded_vendor,
            excluded_binary=excluded_binary,
            excluded_bytes=excluded_bytes,
            included_raw_bytes=sum(item.raw_byte_size for item in observations),
            included_normalized_bytes=sum(item.normalized_byte_size for item in observations),
            included_chunk_count=0,
        )
        return GitRepositorySnapshot(
            repo_name="spen-sdk",
            branch="develop",
            commit_sha=config.commit_sha,
            observations=tuple(observations),
            metrics=metrics,
        )

    def _validate_root(self, root: Path) -> Path:
        if not isinstance(root, Path) or not root.is_absolute() or root.name != "spen-sdk":
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        current = Path(root.anchor)
        try:
            parts = root.parts[1:]
        except (AttributeError, IndexError) as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST) from exc
        for part in parts:
            current = current / part
            if os.path.lexists(current) and _is_reparse_point(current):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        if not root.is_dir():
            raise GitCodeBuildError(GitCodeBuildFailureCategory.INVALID_REQUEST)
        return root

    def _run(self, root: Path, argv: tuple[str, ...], stdin: bytes | None = None) -> GitCommandResult:
        if not _allowed_argv(argv):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        try:
            result = self._runner.run(
                argv=argv,
                cwd=root,
                stdin=stdin,
                timeout_seconds=_TIMEOUT_SECONDS,
                max_stdout_bytes=_STDOUT_CAP,
                max_stderr_bytes=_STDERR_CAP,
            )
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED) from exc
        if type(result) is not GitCommandResult:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        try:
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except Exception as exc:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED) from exc
        if type(returncode) is not int or type(stdout) is not bytes or type(stderr) is not bytes:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        if len(stdout) > _STDOUT_CAP or len(stderr) > _STDERR_CAP:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        if returncode != 0:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_READ_FAILED)
        return result

    def _verify_identity(self, root: Path, config: GitSourceConfig) -> None:
        head = self._run(root, ("rev-parse", "--verify", "HEAD")).stdout
        branch = self._run(root, ("symbolic-ref", "--short", "HEAD")).stdout
        if head != (config.commit_sha + "\n").encode("ascii") or branch != (config.branch + "\n").encode("utf-8"):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.REPOSITORY_IDENTITY_MISMATCH)

    def _read_tree(self, root: Path, config: GitSourceConfig) -> list[tuple[str, str, str]]:
        result = self._run(root, ("ls-tree", "-rz", "--full-tree", config.commit_sha, "--"))
        raw = result.stdout
        if raw and not raw.endswith(b"\x00"):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.TREE_INVALID)
        entries: list[tuple[str, str, str]] = []
        paths: set[str] = set()
        casefold_paths: set[str] = set()
        for record in (raw[:-1].split(b"\x00") if raw else ()):
            try:
                header, path_bytes = record.split(b"\t", 1)
                mode, tree_type, object_id = header.decode("ascii").split(" ")
                path = unicodedata.normalize("NFC", path_bytes.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.TREE_INVALID) from exc
            if (
                tree_type != "blob"
                or mode not in {"100644", "100755"}
                or len(object_id) != 40
                or any(character not in _SHA1 for character in object_id)
            ):
                raise GitCodeBuildError(GitCodeBuildFailureCategory.UNSUPPORTED_TREE_ENTRY)
            _validate_tree_path(path)
            if path in paths or path.casefold() in casefold_paths:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.PATH_COLLISION)
            paths.add(path)
            casefold_paths.add(path.casefold())
            entries.append((mode, object_id, path))
        entries.sort(key=lambda item: item[2])
        return entries

    def _read_blob_sizes(
        self, root: Path, config: GitSourceConfig, entries: Sequence[tuple[str, str, str]]
    ) -> dict[str, int]:
        request = b"".join(object_id.encode("ascii") + b"\n" for _, object_id, _ in entries)
        if len(request) > _STDOUT_CAP:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BUDGET_EXCEEDED)
        result = self._run(root, ("cat-file", "--batch-check"), request)
        if not entries:
            if result.stdout != b"":
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            return {}
        if not result.stdout.endswith(b"\n"):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
        lines = result.stdout[:-1].split(b"\n")
        if len(lines) != len(entries):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
        sizes: dict[str, int] = {}
        for expected, line in zip((object_id for _, object_id, _ in entries), lines, strict=True):
            try:
                object_id, object_type, size_text = line.decode("ascii").split(" ")
                if not size_text.isdigit() or size_text != str(int(size_text)):
                    raise ValueError("invalid blob size")
                size = int(size_text)
            except (UnicodeDecodeError, ValueError) as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED) from exc
            if object_id != expected or object_type != "blob" or size < 0:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            sizes[object_id] = size
        return sizes

    def _read_blobs(
        self, root: Path, config: GitSourceConfig, entries: Sequence[tuple[str, str, int]]
    ) -> dict[str, bytes]:
        request = b"".join(object_id.encode("ascii") + b"\n" for object_id, _, _ in entries)
        result = self._run(root, ("cat-file", "--batch"), request)
        data = result.stdout
        cursor = 0
        blobs: dict[str, bytes] = {}
        for expected, _, expected_size in entries:
            line_end = data.find(b"\n", cursor)
            if line_end < 0:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            try:
                object_id, object_type, size_text = data[cursor:line_end].decode("ascii").split(" ")
                if not size_text.isdigit() or size_text != str(int(size_text)):
                    raise ValueError("invalid blob size")
                size = int(size_text)
            except (UnicodeDecodeError, ValueError) as exc:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED) from exc
            cursor = line_end + 1
            if object_id != expected or object_type != "blob" or size != expected_size:
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            end = cursor + size
            if end >= len(data) or data[end:end + 1] != b"\n":
                raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
            blobs[object_id] = bytes(data[cursor:end])
            cursor = end + 1
        if cursor != len(data):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.BLOB_READ_FAILED)
        return blobs


def _validate_tree_path(path: str) -> None:
    if type(path) is not str or not path or path.startswith("/") or path.endswith("/") or "\\" in path:
        raise GitCodeBuildError(GitCodeBuildFailureCategory.PATH_INVALID)
    components = path.split("/")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
    for component in components:
        if not component or component in {".", ".."} or component.casefold() in reserved:
            raise GitCodeBuildError(GitCodeBuildFailureCategory.PATH_INVALID)
        if component.endswith((".", " ")):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.PATH_INVALID)
        if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in component):
            raise GitCodeBuildError(GitCodeBuildFailureCategory.PATH_INVALID)


def _exclusion_category(path: str) -> str | None:
    components = [component.casefold() for component in path.split("/")]
    if any(component in _GENERATED for component in components):
        return "generated"
    if any(component in _VENDOR for component in components):
        return "vendor"
    return None


def _is_binary_extension(path: str) -> bool:
    return Path(path).suffix.casefold() in _BINARY_EXTENSIONS


def _is_symbol_authority(path: str) -> bool:
    return Path(path).suffix.casefold() in _AUTHORITY_EXTENSIONS


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os, "isjunction", None)
    if callable(is_junction) and is_junction(path):
        return True
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _allowed_argv(argv: tuple[str, ...]) -> bool:
    if argv in {
        ("rev-parse", "--verify", "HEAD"),
        ("symbolic-ref", "--short", "HEAD"),
        ("cat-file", "--batch-check"),
        ("cat-file", "--batch"),
    }:
        return True
    if len(argv) == 5 and argv[:3] == ("ls-tree", "-rz", "--full-tree") and argv[4] == "--":
        commit = argv[3]
        return len(commit) == 40 and all(character in _SHA1 for character in commit)
    return False


__all__ = [
    "GitCommandResult",
    "GitCommandRunner",
    "LocalGitRepositoryReader",
    "SubprocessGitCommandRunner",
]
