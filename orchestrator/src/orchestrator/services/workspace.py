from __future__ import annotations

import base64
import mimetypes
from pathlib import PurePosixPath
import shlex
import time

from orchestrator.domain.models import (
    ExecCommandRequest,
    ExecCommandResult,
    FileDeleteResult,
    FileKind,
    FileListResponse,
    FileNode,
    FileView,
    FileWriteResult,
)
from orchestrator.infra.kubernetes import KubernetesGateway


EXIT_MARKER = "__LITTERBOX_EXIT_CODE__="


class WorkspaceService:
    def __init__(self, gateway: KubernetesGateway) -> None:
        self.gateway = gateway

    @staticmethod
    def normalize_path(path: str | None) -> str:
        if not path:
            return "/workspace"
        if path.startswith("/"):
            return path
        return str(PurePosixPath("/workspace") / path)

    def exec_command(self, sandbox_id: str, request: ExecCommandRequest) -> ExecCommandResult:
        started_at = time.perf_counter()
        stdout, stderr = self.gateway.exec_shell(
            sandbox_id,
            self._build_exec_script(request),
            timeout_seconds=request.timeout,
        )
        execution_time_ms = int((time.perf_counter() - started_at) * 1000)
        exit_code, stderr = self._parse_exec_result(stderr)

        return ExecCommandResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            execution_time_ms=execution_time_ms,
        )

    def get_path(self, sandbox_id: str, path: str, view: FileView) -> tuple[str, FileListResponse | FileNode | bytes]:
        normalized_path = self.normalize_path(path)
        target_kind = self._detect_kind(sandbox_id, normalized_path)

        effective_view = view
        if effective_view == FileView.AUTO:
            effective_view = FileView.CONTENT if target_kind == FileKind.FILE else FileView.LIST

        if target_kind == FileKind.FILE:
            if effective_view != FileView.CONTENT:
                raise ValueError("file targets only support view=auto or view=content")
            return self._guess_media_type(normalized_path), self._read_file_bytes(sandbox_id, normalized_path)

        if effective_view == FileView.CONTENT:
            raise ValueError("directory targets do not support view=content")
        if effective_view == FileView.TREE:
            return "application/json", self._build_tree(sandbox_id, normalized_path)
        return "application/json", self._list_directory(sandbox_id, normalized_path)

    def put_path(self, sandbox_id: str, path: str, kind: FileKind, content: bytes) -> FileWriteResult:
        normalized_path = self.normalize_path(path)
        if kind == FileKind.DIRECTORY:
            script = f"mkdir -p {shlex.quote(normalized_path)}"
            result = self.exec_command(
                sandbox_id,
                ExecCommandRequest(command=["/bin/sh", "-lc", script], workdir="/", timeout=30),
            )
            if result.exit_code != 0:
                raise RuntimeError(result.stderr or "failed to create directory")
            return FileWriteResult(path=normalized_path, kind=kind, size=0)

        encoded = base64.b64encode(content).decode("ascii")
        script = (
            f"mkdir -p \"$(dirname {shlex.quote(normalized_path)})\" && "
            f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(normalized_path)}"
        )
        result = self.exec_command(
            sandbox_id,
            ExecCommandRequest(command=["/bin/sh", "-lc", script], workdir="/", timeout=120),
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "failed to write file")
        return FileWriteResult(path=normalized_path, kind=kind, size=len(content))

    def delete_path(self, sandbox_id: str, path: str, recursive: bool) -> FileDeleteResult:
        normalized_path = self.normalize_path(path)
        if recursive:
            script = f"rm -rf {shlex.quote(normalized_path)}"
        else:
            script = (
                f"if [ -d {shlex.quote(normalized_path)} ]; then "
                f"rmdir {shlex.quote(normalized_path)}; "
                f"else rm -f {shlex.quote(normalized_path)}; fi"
            )
        result = self.exec_command(
            sandbox_id,
            ExecCommandRequest(command=["/bin/sh", "-lc", script], workdir="/", timeout=30),
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "failed to delete path")
        return FileDeleteResult(path=normalized_path)

    def _detect_kind(self, sandbox_id: str, path: str) -> FileKind:
        result = self.exec_command(
            sandbox_id,
            ExecCommandRequest(
                command=[
                    "/bin/sh",
                    "-lc",
                    (
                        f"if [ -d {shlex.quote(path)} ]; then printf directory; "
                        f"elif [ -f {shlex.quote(path)} ]; then printf file; "
                        "else printf missing; fi"
                    ),
                ],
                workdir="/",
                timeout=15,
            ),
        )
        kind = result.stdout.strip()
        if kind == "directory":
            return FileKind.DIRECTORY
        if kind == "file":
            return FileKind.FILE
        raise FileNotFoundError(path)

    def _read_file_bytes(self, sandbox_id: str, path: str) -> bytes:
        result = self.exec_command(
            sandbox_id,
            ExecCommandRequest(
                command=["/bin/sh", "-lc", f"base64 < {shlex.quote(path)}"],
                workdir="/",
                timeout=120,
            ),
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "failed to read file")
        encoded = "".join(result.stdout.splitlines())
        return base64.b64decode(encoded.encode("ascii")) if encoded else b""

    def _list_directory(self, sandbox_id: str, path: str) -> FileListResponse:
        lines = self._scan_directory(sandbox_id, path, recursive=False)
        entries = [
            FileNode(
                name=PurePosixPath(entry_path).name,
                path=entry_path,
                is_dir=kind == FileKind.DIRECTORY,
            )
            for kind, entry_path in lines
        ]
        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        return FileListResponse(path=path, is_dir=True, entries=entries)

    def _build_tree(self, sandbox_id: str, path: str) -> FileNode:
        root = FileNode(
            name=PurePosixPath(path).name or path,
            path=path,
            is_dir=True,
        )
        node_map: dict[str, FileNode] = {path: root}
        for kind, entry_path in self._scan_directory(sandbox_id, path, recursive=True):
            node = FileNode(
                name=PurePosixPath(entry_path).name,
                path=entry_path,
                is_dir=kind == FileKind.DIRECTORY,
            )
            node_map[entry_path] = node
            parent = node_map.get(str(PurePosixPath(entry_path).parent))
            if parent is not None:
                parent.children.append(node)

        for node in node_map.values():
            node.children.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        return root

    def _scan_directory(self, sandbox_id: str, path: str, recursive: bool) -> list[tuple[FileKind, str]]:
        maxdepth = "" if recursive else "-maxdepth 1"
        script = (
            f"find {shlex.quote(path)} -mindepth 1 {maxdepth} -print 2>/dev/null | sort | "
            "while IFS= read -r p; do "
            'if [ -d "$p" ]; then printf "d\\t%s\\n" "$p"; '
            'else printf "f\\t%s\\n" "$p"; fi; '
            "done"
        )
        result = self.exec_command(
            sandbox_id,
            ExecCommandRequest(command=["/bin/sh", "-lc", script], workdir="/", timeout=120),
        )
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "failed to list directory")

        lines: list[tuple[FileKind, str]] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            kind_code, entry_path = line.split("\t", 1)
            lines.append((FileKind.DIRECTORY if kind_code == "d" else FileKind.FILE, entry_path))
        return lines

    def _build_exec_script(self, request: ExecCommandRequest) -> str:
        return (
            "__lb_exit=0\n"
            f"{self._build_workdir_script(request.workdir)}\n"
            'if [ "$__lb_exit" -eq 0 ]; then\n'
            f"  {shlex.join(request.command)}\n"
            "  __lb_exit=$?\n"
            "fi\n"
            f"printf '\\n{EXIT_MARKER}%s\\n' \"$__lb_exit\" >&2\n"
        )

    def _build_workdir_script(self, workdir: str | None) -> str:
        if workdir:
            normalized_path = self.normalize_path(workdir)
            return f"cd {shlex.quote(normalized_path)} 2>/dev/null || __lb_exit=$?"
        return "cd /workspace 2>/dev/null || cd /home 2>/dev/null || cd / || true"

    @staticmethod
    def _parse_exec_result(stderr: str) -> tuple[int, str]:
        lines = stderr.splitlines()
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx].strip()
            if line.startswith(EXIT_MARKER):
                exit_code = int(line.split("=", 1)[1])
                cleaned = "\n".join(lines[:idx]).strip()
                return exit_code, cleaned
        raise RuntimeError("missing exec exit marker")

    @staticmethod
    def _guess_media_type(path: str) -> str:
        media_type, _ = mimetypes.guess_type(path)
        return media_type or "application/octet-stream"
