import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.incidents import IncidentResponse, UpdateIncidentRequest
from app.core.deps import require_role
from app.db.session import get_db
from app.models.enums import IncidentStatus
from app.models.incident import Incident
from app.services.incidents import update_incident

router = APIRouter(
    prefix="/admin/incidents",
    tags=["admin"],
    dependencies=[Depends(require_role("ADMIN", "SECURITY_REVIEWER"))],
)


async def _get_or_404(db: AsyncSession, incident_id: uuid.UUID) -> Incident:
    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident not found")
    return incident


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    status_filter: str | None = None, severity_filter: str | None = None, db: AsyncSession = Depends(get_db)
) -> list[IncidentResponse]:
    query = select(Incident).order_by(Incident.created_at.desc())
    if status_filter:
        query = query.where(Incident.status == status_filter)
    if severity_filter:
        query = query.where(Incident.severity == severity_filter)
    result = await db.execute(query)
    return [IncidentResponse.from_model(i) for i in result.scalars()]


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> IncidentResponse:
    incident = await _get_or_404(db, incident_id)
    return IncidentResponse.from_model(incident)


@router.put("/{incident_id}", response_model=IncidentResponse)
async def update_incident_endpoint(
    incident_id: uuid.UUID, payload: UpdateIncidentRequest, db: AsyncSession = Depends(get_db)
) -> IncidentResponse:
    incident = await _get_or_404(db, incident_id)

    status_value = None
    if payload.status is not None:
        try:
            status_value = IncidentStatus(payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown status: {payload.status}") from exc

    await update_incident(
        db, incident, status_value=status_value, assigned_to=payload.assigned_to, resolution=payload.resolution
    )
    await db.commit()
    # `updated_at` has a server-side ON UPDATE trigger, which SQLAlchemy
    # marks expired after a flush that touches the row regardless of
    # expire_on_commit — a bare attribute access would otherwise trigger an
    # implicit lazy-load SELECT outside the async greenlet bridge
    # (raises MissingGreenlet). Refresh explicitly instead.
    await db.refresh(incident)
    return IncidentResponse.from_model(incident)
