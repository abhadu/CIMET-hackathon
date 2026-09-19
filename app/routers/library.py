from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, func, select

from app.db import get_session
from app.models import Check, CheckLibraryVersion
from app.schemas import LibraryVersionOut
from app.services.check_library import LibraryExport, import_library, list_versions, load_checks

router = APIRouter(prefix="/api/library", tags=["check-library"])


@router.get("", response_model=list[LibraryVersionOut])
def versions(retailer_id: str | None = None, session: Session = Depends(get_session)) -> list[LibraryVersionOut]:
    counts = dict(
        session.exec(select(Check.library_version_id, func.count(Check.id)).group_by(Check.library_version_id)).all()
    )
    return [
        LibraryVersionOut(
            id=v.id or 0,
            retailer_id=v.retailer_id,
            version=v.version,
            effective_from=v.effective_from,
            notes=v.notes,
            check_count=counts.get(v.id, 0),
        )
        for v in list_versions(session, retailer_id)
    ]


@router.get("/{version_id}/checks", response_model=list[Check])
def checks(version_id: int, session: Session = Depends(get_session)) -> list[Check]:
    if session.get(CheckLibraryVersion, version_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown library version")
    return load_checks(session, version_id)


@router.post("/import", response_model=LibraryVersionOut, status_code=status.HTTP_201_CREATED)
def import_export(payload: LibraryExport, session: Session = Depends(get_session)) -> LibraryVersionOut:
    version = import_library(session, payload)
    return LibraryVersionOut(
        id=version.id or 0,
        retailer_id=version.retailer_id,
        version=version.version,
        effective_from=version.effective_from,
        notes=version.notes,
        check_count=len(payload.checks),
    )
