from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project, ProjectMember, SourceArtifact


class ProjectRepository:
    """项目数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, project_id: UUID) -> Project | None:
        """按标识查询项目。"""

        return await self.session.get(Project, project_id)

    async def list_all(self) -> list[Project]:
        """查询全部项目。"""

        return list(await self.session.scalars(select(Project).order_by(Project.created_at.desc())))

    async def list_by_user_id(self, user_id: UUID) -> list[Project]:
        """查询用户已获授权的项目。"""

        statement = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return list(await self.session.scalars(statement))

    async def has_member(self, project_id: UUID, user_id: UUID) -> bool:
        """判断用户是否具备项目访问授权。"""

        statement = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        return await self.session.scalar(statement) is not None

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        """查询项目成员。"""

        statement = select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.user_id)
        return list(await self.session.scalars(statement))

    def add_project(self, project: Project) -> None:
        """加入待持久化项目。"""

        self.session.add(project)

    def add_member(self, member: ProjectMember) -> None:
        """加入待持久化成员授权。"""

        self.session.add(member)

    async def remove_member(self, project_id: UUID, user_id: UUID) -> bool:
        """移除项目成员。"""

        member = await self.session.get(ProjectMember, {"project_id": project_id, "user_id": user_id})
        if member is None:
            return False
        await self.session.delete(member)
        return True

    async def delete_project(self, project: Project) -> None:
        """删除项目。"""

        await self.session.delete(project)

    async def get_source_artifact(self, project_id: UUID) -> SourceArtifact | None:
        statement = select(SourceArtifact).where(SourceArtifact.project_id == project_id).order_by(SourceArtifact.created_at.desc())
        return await self.session.scalar(statement)

    async def get_source_artifact_by_id(self, artifact_id: UUID) -> SourceArtifact | None:
        return await self.session.get(SourceArtifact, artifact_id)

    async def replace_source_artifact(self, artifact: SourceArtifact) -> None:
        """保存新的源码来源，并保留历史扫描对应的来源记录。"""

        self.session.add(artifact)
