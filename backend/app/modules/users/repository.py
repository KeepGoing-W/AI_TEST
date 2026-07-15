from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


class UserRepository:
    """用户数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """按标识查询用户。"""

        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        """按用户名查询用户。"""

        statement = select(User).where(User.username == username)
        return await self.session.scalar(statement)

    def add(self, user: User) -> None:
        """加入待持久化用户。"""

        self.session.add(user)
