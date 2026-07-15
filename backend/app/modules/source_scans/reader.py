import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from app.config import Settings
from app.modules.projects.models import SourceArtifact, SourceType

IGNORED_DIRECTORIES = {".git", ".gradle", ".hg", ".idea", ".svn", "build", "node_modules", "out", "target"}
SENSITIVE_FILE_NAMES = {"credentials", "id_rsa", "keystore", "secrets"}
SENSITIVE_SUFFIXES = {".cer", ".crt", ".key", ".p12", ".pem", ".pfx", ".jks"}


class SourceReadError(Exception):
    """表示可安全反馈的源码读取失败。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DiscoveredSourceFile:
    """已读取且待持久化的 Java 源文件。"""

    relative_path: str
    content: str
    content_sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SourceDiscoveryResult:
    """一次文件发现的结果与统计。"""

    files: list[DiscoveredSourceFile]
    ignored_file_count: int
    total_bytes: int

    def summary(self) -> dict[str, object]:
        return {
            "sourceFiles": len(self.files),
            "ignoredFiles": self.ignored_file_count,
            "totalBytes": self.total_bytes,
        }


def discover_java_files(artifact: SourceArtifact, settings: Settings) -> SourceDiscoveryResult:
    """从登记的本地目录或 ZIP 中受控读取 Java 源文件。"""

    if artifact.source_type == SourceType.LOCAL_PATH:
        return _discover_local_java_files(Path(artifact.storage_location), settings)
    if artifact.source_type == SourceType.ZIP_UPLOAD:
        return _discover_zip_java_files(Path(artifact.storage_location), settings)
    raise SourceReadError("SOURCE_ARTIFACT_INVALID", "源码来源类型无效")


def _discover_local_java_files(root: Path, settings: Settings) -> SourceDiscoveryResult:
    resolved_root = _validate_local_root(root, settings)
    files: list[DiscoveredSourceFile] = []
    ignored_file_count = 0
    total_bytes = 0
    processed_file_count = 0
    for directory, directory_names, file_names in os.walk(resolved_root, topdown=True, followlinks=False):
        directory_names[:] = [name for name in directory_names if name.lower() not in IGNORED_DIRECTORIES]
        for file_name in file_names:
            path = Path(directory, file_name)
            relative_path = path.relative_to(resolved_root)
            if _should_ignore(relative_path):
                ignored_file_count += 1
                continue
            try:
                resolved_path = path.resolve(strict=True)
            except OSError as exc:
                raise SourceReadError("SOURCE_FILE_READ_FAILED", "源码文件读取失败") from exc
            if not resolved_path.is_relative_to(resolved_root):
                raise SourceReadError("SOURCE_PATH_NOT_ALLOWED", "源码文件不在登记目录内")
            if not resolved_path.is_file():
                ignored_file_count += 1
                continue
            try:
                size_bytes = resolved_path.stat().st_size
            except OSError as exc:
                raise SourceReadError("SOURCE_FILE_READ_FAILED", "源码文件读取失败") from exc
            _validate_file_size(size_bytes, settings)
            total_bytes = _validate_limits(processed_file_count, total_bytes, size_bytes, settings)
            processed_file_count += 1
            try:
                content_bytes = resolved_path.read_bytes()
            except OSError as exc:
                raise SourceReadError("SOURCE_FILE_READ_FAILED", "源码文件读取失败") from exc
            content = _read_java_file(content_bytes, size_bytes)
            if content is None:
                ignored_file_count += 1
                continue
            files.append(_to_discovered_file(relative_path.as_posix(), content, content_bytes, size_bytes))
    return SourceDiscoveryResult(files=files, ignored_file_count=ignored_file_count, total_bytes=total_bytes)


def _discover_zip_java_files(archive_path: Path, settings: Settings) -> SourceDiscoveryResult:
    resolved_archive = _validate_uploaded_archive(archive_path, settings)
    files: list[DiscoveredSourceFile] = []
    ignored_file_count = 0
    total_bytes = 0
    processed_file_count = 0
    try:
        with ZipFile(resolved_archive) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                relative_path = _validate_zip_entry_path(entry.filename)
                if _should_ignore(relative_path):
                    ignored_file_count += 1
                    continue
                _validate_file_size(entry.file_size, settings)
                total_bytes = _validate_limits(processed_file_count, total_bytes, entry.file_size, settings)
                processed_file_count += 1
                content_bytes = archive.read(entry)
                content = _read_java_file(content_bytes, entry.file_size)
                if content is None:
                    ignored_file_count += 1
                    continue
                files.append(_to_discovered_file(relative_path.as_posix(), content, content_bytes, entry.file_size))
    except BadZipFile as exc:
        raise SourceReadError("SOURCE_ARCHIVE_INVALID", "源码压缩包格式无效") from exc
    except OSError as exc:
        raise SourceReadError("SOURCE_ARCHIVE_NOT_FOUND", "源码压缩包不可访问") from exc
    return SourceDiscoveryResult(files=files, ignored_file_count=ignored_file_count, total_bytes=total_bytes)


def _validate_local_root(root: Path, settings: Settings) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        allowed_roots = [
            Path(item.strip()).resolve(strict=True)
            for item in settings.source_root_allowlist.split(",")
            if item.strip()
        ]
    except OSError as exc:
        raise SourceReadError("SOURCE_PATH_NOT_ALLOWED", "源码目录不可访问") from exc
    if not resolved_root.is_dir() or not any(
        resolved_root.is_relative_to(allowed_root) for allowed_root in allowed_roots
    ):
        raise SourceReadError("SOURCE_PATH_NOT_ALLOWED", "源码目录不在允许范围内")
    return resolved_root


def validate_local_source_root(root: Path, settings: Settings) -> Path:
    """供受控检索复用本地源码根目录边界校验。"""

    return _validate_local_root(root, settings)


def _validate_uploaded_archive(archive_path: Path, settings: Settings) -> Path:
    try:
        resolved_archive = archive_path.resolve(strict=True)
    except OSError as exc:
        raise SourceReadError("SOURCE_ARCHIVE_NOT_FOUND", "源码压缩包不可访问") from exc
    upload_root = settings.source_upload_root.resolve()
    if not resolved_archive.is_file() or not resolved_archive.is_relative_to(upload_root):
        raise SourceReadError("SOURCE_PATH_NOT_ALLOWED", "源码压缩包不在允许范围内")
    return resolved_archive


def _validate_zip_entry_path(value: str) -> Path:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise SourceReadError("SOURCE_ARCHIVE_INVALID", "源码压缩包包含非法路径")
    return Path(*path.parts)


def _should_ignore(relative_path: Path) -> bool:
    name = relative_path.name.lower()
    if any(part.lower() in IGNORED_DIRECTORIES for part in relative_path.parts[:-1]):
        return True
    if name.startswith(".env") or name in SENSITIVE_FILE_NAMES or relative_path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return relative_path.suffix.lower() != ".java"


def _read_java_file(content_bytes: bytes, size_bytes: int) -> str | None:
    if len(content_bytes) != size_bytes:
        raise SourceReadError("SOURCE_FILE_READ_FAILED", "源码文件读取不完整")
    try:
        return content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _validate_limits(
    processed_file_count: int, total_bytes: int, file_size: int, settings: Settings
) -> int:
    if processed_file_count >= settings.max_source_file_count:
        raise SourceReadError("SOURCE_FILE_COUNT_EXCEEDED", "源码文件数量超过限制")
    next_total_bytes = total_bytes + file_size
    if next_total_bytes > settings.max_source_total_bytes:
        raise SourceReadError("SOURCE_TOTAL_SIZE_EXCEEDED", "源码总大小超过限制")
    return next_total_bytes


def _validate_file_size(size_bytes: int, settings: Settings) -> None:
    if size_bytes > settings.max_source_file_bytes:
        raise SourceReadError("SOURCE_FILE_TOO_LARGE", "源码文件超过大小限制")


def _to_discovered_file(
    relative_path: str, content: str, content_bytes: bytes, size_bytes: int
) -> DiscoveredSourceFile:
    return DiscoveredSourceFile(
        relative_path=relative_path,
        content=content,
        content_sha256=hashlib.sha256(content_bytes).hexdigest(),
        size_bytes=size_bytes,
    )
