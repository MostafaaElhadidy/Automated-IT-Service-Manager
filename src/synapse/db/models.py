from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from synapse.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="end_user")  # end_user|it_team|admin
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConfigurationItem(Base):
    __tablename__ = "configuration_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    ci_type: Mapped[str] = mapped_column(String(32), nullable=False)  # server|app|db|network|lb|cache
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="operational")
    criticality: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # 1=highest

    upstream: Mapped[list[CIRelationship]] = relationship(
        "CIRelationship",
        foreign_keys="CIRelationship.source_id",
        back_populates="source",
        lazy="selectin",
    )
    downstream: Mapped[list[CIRelationship]] = relationship(
        "CIRelationship",
        foreign_keys="CIRelationship.target_id",
        back_populates="target",
        lazy="selectin",
    )


class CIRelationship(Base):
    __tablename__ = "ci_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("configuration_items.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("configuration_items.id"), nullable=False)
    rel_type: Mapped[str] = mapped_column(String(32), nullable=False)  # depends_on|hosts|connects_to

    source: Mapped[ConfigurationItem] = relationship(
        "ConfigurationItem", foreign_keys=[source_id], back_populates="upstream"
    )
    target: Mapped[ConfigurationItem] = relationship(
        "ConfigurationItem", foreign_keys=[target_id], back_populates="downstream"
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    affected_ci: Mapped[str | None] = mapped_column(
        ForeignKey("configuration_items.id"), nullable=True
    )
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    action_logs: Mapped[list[ActionLog]] = relationship(
        "ActionLog", back_populates="ticket", lazy="selectin"
    )
    reports: Mapped[list[Report]] = relationship(
        "Report", back_populates="ticket", lazy="selectin"
    )


class ActionLog(Base):
    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    runbook_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # proposed|approved|executed|failed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="action_logs")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="reports")
