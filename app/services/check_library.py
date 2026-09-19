from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from app.models import Check, CheckLibraryVersion, CheckType


class CheckDefinition(BaseModel):
    code: str
    name: str
    type: CheckType
    critical: bool = False
    weight: float = Field(gt=0)
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("critical")
    @classmethod
    def behaviour_never_critical(cls, value: bool, info) -> bool:
        if value and info.data.get("type") == CheckType.BEHAVIOUR:
            raise ValueError("behaviour checks cannot be critical")
        return value


class LibraryExport(BaseModel):
    retailer_id: str
    version: str
    effective_from: date
    notes: str | None = None
    checks: list[CheckDefinition]


def import_library(session: Session, export: LibraryExport) -> CheckLibraryVersion:
    existing = session.exec(
        select(CheckLibraryVersion).where(
            CheckLibraryVersion.retailer_id == export.retailer_id,
            CheckLibraryVersion.version == export.version,
        )
    ).first()
    if existing:
        return existing
    version = CheckLibraryVersion(
        retailer_id=export.retailer_id,
        version=export.version,
        effective_from=export.effective_from,
        notes=export.notes,
    )
    session.add(version)
    session.flush()
    for definition in export.checks:
        session.add(
            Check(
                library_version_id=version.id or 0,
                code=definition.code,
                name=definition.name,
                check_type=definition.type,
                is_critical=definition.critical,
                weight=definition.weight,
                tags=definition.tags,
                config=definition.config,
            )
        )
    session.commit()
    session.refresh(version)
    return version


def resolve_version(session: Session, retailer_id: str, call_date: date) -> CheckLibraryVersion | None:
    return session.exec(
        select(CheckLibraryVersion)
        .where(CheckLibraryVersion.retailer_id == retailer_id, CheckLibraryVersion.effective_from <= call_date)
        .order_by(CheckLibraryVersion.effective_from.desc(), CheckLibraryVersion.id.desc())  # type: ignore[union-attr]
    ).first()


def load_checks(session: Session, version_id: int) -> list[Check]:
    return list(session.exec(select(Check).where(Check.library_version_id == version_id).order_by(Check.id)))


def list_versions(session: Session, retailer_id: str | None = None) -> list[CheckLibraryVersion]:
    query = select(CheckLibraryVersion)
    if retailer_id:
        query = query.where(CheckLibraryVersion.retailer_id == retailer_id)
    return list(session.exec(query.order_by(CheckLibraryVersion.retailer_id, CheckLibraryVersion.effective_from)))
