from datetime import datetime
from enum import Enum
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EnumType = TypeVar("EnumType", bound=Enum)


def enum_values(enum_type: type[EnumType]) -> list[str]:
    """让 SQLAlchemy 持久化字符串枚举值，而不是 Python 成员名。"""

    return [str(item.value) for item in enum_type]


class Base(DeclarativeBase):
    """所有数据库模型的声明基类。"""


class UUIDPrimaryKeyMixin:
    """为实体提供 UUID 主键。"""

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    """为实体提供 UTC 时间戳字段。"""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
