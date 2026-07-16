from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.common.network import NetworkTargetError, approve_http_target, validate_host_allowlist
from app.config import get_settings
from app.modules.projects.models import OpenApiSourceType, Project, ProjectMember, SourceArtifact, SourceType
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import CreateProjectRequest, UpdateProjectRequest
from app.modules.users.repository import UserRepository


async def create_project(session: AsyncSession, payload: CreateProjectRequest, creator_id: UUID) -> Project:
    """创建项目，并将创建者加入项目成员。"""

    repository = ProjectRepository(session)
    project = Project(name=payload.name, description=payload.description, created_by=creator_id)
    repository.add_project(project)
    await session.flush()
    repository.add_member(ProjectMember(project_id=project.id, user_id=creator_id))
    await session.commit()
    await session.refresh(project)
    return project


async def update_project(session: AsyncSession, project: Project, payload: UpdateProjectRequest) -> Project:
    """更新项目基础信息。"""

    updates = payload.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        setattr(project, field_name, value)
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    """删除项目及其成员授权。"""

    await ProjectRepository(session).delete_project(project)
    await session.commit()


async def add_project_member(session: AsyncSession, project_id: UUID, user_id: UUID) -> ProjectMember:
    """为项目添加已启用测试成员。"""

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    if not user.is_active:
        raise AppError("AUTH_USER_DISABLED", "用户已被禁用", 403)

    repository = ProjectRepository(session)
    if await repository.has_member(project_id, user_id):
        raise AppError("PROJECT_MEMBER_EXISTS", "用户已具备项目访问权限", 409)

    member = ProjectMember(project_id=project_id, user_id=user_id)
    repository.add_member(member)
    await session.commit()
    return member


async def remove_project_member(session: AsyncSession, project_id: UUID, user_id: UUID) -> None:
    """移除项目成员授权。"""

    if not await ProjectRepository(session).remove_member(project_id, user_id):
        raise AppError("PROJECT_MEMBER_NOT_FOUND", "项目成员不存在", 404)
    await session.commit()


def validate_local_source_path(path: str) -> str:
    """校验目录位于配置的受控根目录。"""

    try:
        candidate = Path(path).resolve(strict=True)
        settings = get_settings()
        roots = [Path(item.strip()).resolve(strict=True) for item in settings.source_root_allowlist.split(",") if item.strip()]
    except OSError as exc:
        raise AppError("SOURCE_PATH_NOT_ALLOWED", "源码目录不在允许范围内", 400) from exc
    if not candidate.is_dir() or not any(candidate.is_relative_to(root) for root in roots):
        raise AppError("SOURCE_PATH_NOT_ALLOWED", "源码目录不在允许范围内", 400)
    return str(candidate)


async def configure_local_source(session: AsyncSession, project_id: UUID, path: str, user_id: UUID) -> SourceArtifact:
    """登记本地源码目录。"""

    artifact = SourceArtifact(project_id=project_id, source_type=SourceType.LOCAL_PATH, storage_location=validate_local_source_path(path), created_by=user_id)
    await ProjectRepository(session).replace_source_artifact(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def configure_zip_source(session: AsyncSession, project_id: UUID, content: bytes, filename: str, user_id: UUID) -> SourceArtifact:
    """校验并保存 ZIP 源码包。"""

    settings = get_settings()
    if len(content) > settings.max_source_archive_bytes:
        raise AppError("SOURCE_ARCHIVE_TOO_LARGE", "源码压缩包超过大小限制", 400)
    destination = settings.source_upload_root.resolve() / f"{uuid4()}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    try:
        with ZipFile(destination) as archive:
            if any(
                Path(item.filename).is_absolute()
                or ".." in Path(item.filename.replace("\\", "/")).parts
                or _is_zip_symlink(item.external_attr)
                for item in archive.infolist()
            ):
                raise AppError("SOURCE_ARCHIVE_INVALID", "源码压缩包包含非法路径", 400)
    except (AppError, BadZipFile) as exc:
        destination.unlink(missing_ok=True)
        if isinstance(exc, AppError):
            raise
        raise AppError("SOURCE_ARCHIVE_INVALID", "源码压缩包格式无效", 400) from exc
    artifact = SourceArtifact(project_id=project_id, source_type=SourceType.ZIP_UPLOAD, storage_location=str(destination), original_name=filename, size_bytes=len(content), created_by=user_id)
    await ProjectRepository(session).replace_source_artifact(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


async def configure_openapi_url(session: AsyncSession, project: Project, url: str) -> Project:
    try:
        allowlist = validate_host_allowlist(
            [item for item in get_settings().openapi_host_allowlist.split(",") if item.strip()]
        )
        await approve_http_target(url, allowlist)
    except NetworkTargetError as exc:
        code = "OPENAPI_HOST_NOT_ALLOWED" if exc.reason == "host_not_allowed" else "OPENAPI_URL_INVALID"
        raise AppError(code, "OpenAPI 地址不在受控范围内" if code.endswith("NOT_ALLOWED") else "OpenAPI 地址无效", 400) from exc
    project.openapi_source_type = OpenApiSourceType.URL
    project.openapi_location = url
    await session.commit()
    await session.refresh(project)
    return project


def _is_zip_symlink(external_attr: int) -> bool:
    return (external_attr >> 16) & 0o170000 == 0o120000


async def configure_openapi_file(session: AsyncSession, project: Project, content: bytes, filename: str) -> Project:
    """保存受控 OpenAPI 文件来源。"""

    if len(content) > get_settings().max_openapi_document_bytes:
        raise AppError("OPENAPI_DOCUMENT_TOO_LARGE", "OpenAPI 文件超过大小限制", 400)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".json", ".yaml", ".yml"}:
        raise AppError("OPENAPI_FILE_INVALID", "OpenAPI 文件格式无效", 400)
    destination = get_settings().source_upload_root.resolve() / "openapi" / f"{uuid4()}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    project.openapi_source_type = OpenApiSourceType.FILE
    project.openapi_location = str(destination)
    await session.commit()
    await session.refresh(project)
    return project
