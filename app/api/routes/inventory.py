"""
> Why: Provide tenant-scoped appliance, technician, and service-history endpoints.
> Throughput: Indexed list and item operations scoped through active household membership.
> Dependencies: FastAPI, Pydantic, SQLAlchemy, and shared authorization lookups.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.dependencies import AuthenticatedUser, DbSession, require_membership
from app.api.schemas import (
    ApplianceCreate,
    ApplianceRead,
    ApplianceUpdate,
    ServiceRecordCreate,
    ServiceRecordRead,
    ServiceRecordUpdate,
    TechnicianCreate,
    TechnicianRead,
    TechnicianUpdate,
)
from app.db.models import (
    Appliance,
    ApplianceStatus,
    ApplianceTechnician,
    HouseholdMembership,
    Property,
    ServiceRecord,
    Technician,
)
from app.services.authorization import (
    get_accessible_appliance,
    get_accessible_property,
    get_accessible_service_record,
    get_accessible_technician,
    not_found,
)
from app.services.qr_gateway import (
    invalidate_appliance_qr_cache,
    invalidate_technician_qr_cache,
)

router = APIRouter(prefix="/v1", tags=["inventory"])


@router.get("/appliances", response_model=list[ApplianceRead], summary="List appliances")
def list_appliances(
    user: AuthenticatedUser,
    db: DbSession,
    property_id: UUID | None = Query(default=None, description="Limit results to one property."),
) -> list[Appliance]:
    """List active appliances in the caller's accessible properties."""
    query = (
        select(Appliance)
        .join(Property, Property.id == Appliance.property_id)
        .join(HouseholdMembership, HouseholdMembership.household_id == Property.household_id)
        .where(
            Appliance.status == ApplianceStatus.ACTIVE.value,
            Property.archived_at.is_(None),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
        .order_by(Appliance.created_at, Appliance.id)
    )
    if property_id is not None:
        query = query.where(Property.id == property_id)
    return list(db.scalars(query).all())


@router.post(
    "/appliances",
    response_model=ApplianceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an appliance",
)
def create_appliance(
    payload: ApplianceCreate,
    user: AuthenticatedUser,
    db: DbSession,
) -> Appliance:
    """Create an appliance only inside an active accessible property."""
    get_accessible_property(db, user, payload.property_id)
    appliance = Appliance(**payload.model_dump())
    db.add(appliance)
    db.commit()
    db.refresh(appliance)
    return appliance


@router.get(
    "/appliances/{appliance_id}",
    response_model=ApplianceRead,
    summary="Read an appliance",
)
def read_appliance(
    appliance_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> Appliance:
    """Read one active appliance in an accessible household."""
    return get_accessible_appliance(db, user, appliance_id)


@router.patch(
    "/service-records/{service_record_id}",
    response_model=ServiceRecordRead,
    summary="Correct an appliance service event",
)
def update_service_record(
    service_record_id: UUID,
    payload: ServiceRecordUpdate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> ServiceRecord:
    """Correct a service event only within an accessible appliance."""
    service_record = get_accessible_service_record(db, user, service_record_id)
    appliance = get_accessible_appliance(db, user, service_record.appliance_id)
    property_record = db.get(Property, appliance.property_id)
    updates = payload.model_dump(exclude_unset=True)
    for required_field in ("serviced_at", "description", "is_public"):
        if required_field in updates and updates[required_field] is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_service_record",
                    "message": f"{required_field} cannot be null.",
                },
            )
    technician_id = updates.get("technician_id")
    if technician_id is not None:
        technician = get_accessible_technician(db, user, technician_id)
        if property_record is None or technician.household_id != property_record.household_id:
            raise not_found()
        association = db.scalar(
            select(ApplianceTechnician).where(
                ApplianceTechnician.appliance_id == appliance.id,
                ApplianceTechnician.technician_id == technician.id,
            )
        )
        if association is None:
            db.add(
                ApplianceTechnician(
                    appliance_id=appliance.id,
                    technician_id=technician.id,
                    is_primary=False,
                )
            )
    for field, value in updates.items():
        setattr(service_record, field, value)
    db.commit()
    db.refresh(service_record)
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return service_record


@router.delete(
    "/service-records/{service_record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an appliance service event",
)
def delete_service_record(
    service_record_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Response:
    """Delete a service event only within an accessible appliance."""
    service_record = get_accessible_service_record(db, user, service_record_id)
    appliance_id = service_record.appliance_id
    db.delete(service_record)
    db.commit()
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/technicians/{technician_id}",
    response_model=TechnicianRead,
    summary="Read a technician contact",
)
def read_technician(
    technician_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> Technician:
    """Read a technician from an accessible household."""
    return get_accessible_technician(db, user, technician_id)


@router.patch(
    "/appliances/{appliance_id}",
    response_model=ApplianceRead,
    summary="Update an appliance",
)
def update_appliance(
    appliance_id: UUID,
    payload: ApplianceUpdate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Appliance:
    """Update private appliance details without allowing a tenant/property move."""
    appliance = get_accessible_appliance(db, user, appliance_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_name", "message": "Appliance name cannot be null."},
        )
    for field, value in updates.items():
        setattr(appliance, field, value)
    db.commit()
    db.refresh(appliance)
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return appliance


@router.delete(
    "/appliances/{appliance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Archive an appliance",
)
def archive_appliance(
    appliance_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Response:
    """Archive an appliance while preserving its historical records."""
    appliance = get_accessible_appliance(db, user, appliance_id)
    appliance.status = ApplianceStatus.ARCHIVED.value
    db.commit()
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/technicians", response_model=list[TechnicianRead], summary="List technicians")
def list_technicians(
    user: AuthenticatedUser,
    db: DbSession,
    household_id: UUID = Query(description="Household whose technician directory to list."),
) -> list[Technician]:
    """List active technician entries in an accessible household."""
    require_membership(db, user, household_id)
    return list(
        db.scalars(
            select(Technician)
            .where(
                Technician.household_id == household_id,
                Technician.is_active.is_(True),
            )
            .order_by(Technician.name, Technician.id)
        ).all()
    )


@router.post(
    "/technicians",
    response_model=TechnicianRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a technician contact",
)
def create_technician(
    payload: TechnicianCreate,
    user: AuthenticatedUser,
    db: DbSession,
) -> Technician:
    """Create a private technician directory entry for an accessible household."""
    require_membership(db, user, payload.household_id)
    technician = Technician(**payload.model_dump())
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return technician


@router.patch(
    "/technicians/{technician_id}",
    response_model=TechnicianRead,
    summary="Update a technician contact",
)
def update_technician(
    technician_id: UUID,
    payload: TechnicianUpdate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Technician:
    """Update a technician entry in an accessible household."""
    technician = get_accessible_technician(db, user, technician_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_name", "message": "Technician name cannot be null."},
        )
    for field, value in updates.items():
        setattr(technician, field, value)
    db.commit()
    db.refresh(technician)
    invalidate_technician_qr_cache(db, request.app.state.redis, technician.id)
    return technician


@router.delete(
    "/technicians/{technician_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Deactivate a technician contact",
)
def deactivate_technician(
    technician_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Response:
    """Deactivate a directory entry without deleting historical service attribution."""
    technician = get_accessible_technician(db, user, technician_id)
    technician.is_active = False
    db.commit()
    invalidate_technician_qr_cache(db, request.app.state.redis, technician.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/appliances/{appliance_id}/service-records",
    response_model=list[ServiceRecordRead],
    summary="List appliance service history",
)
def list_service_records(
    appliance_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> list[ServiceRecord]:
    """List service history only for an accessible appliance."""
    get_accessible_appliance(db, user, appliance_id)
    return list(
        db.scalars(
            select(ServiceRecord)
            .where(ServiceRecord.appliance_id == appliance_id)
            .order_by(ServiceRecord.serviced_at.desc(), ServiceRecord.id)
        ).all()
    )


@router.post(
    "/appliances/{appliance_id}/service-records",
    response_model=ServiceRecordRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an appliance service event",
)
def create_service_record(
    appliance_id: UUID,
    payload: ServiceRecordCreate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> ServiceRecord:
    """Create a service event and optionally associate a same-household technician."""
    appliance = get_accessible_appliance(db, user, appliance_id)
    if payload.technician_id is not None:
        technician = get_accessible_technician(db, user, payload.technician_id)
        property_record = db.get(Property, appliance.property_id)
        if property_record is None or technician.household_id != property_record.household_id:
            raise not_found()
        association = db.scalar(
            select(ApplianceTechnician).where(
                ApplianceTechnician.appliance_id == appliance.id,
                ApplianceTechnician.technician_id == technician.id,
            )
        )
        if association is None:
            db.add(
                ApplianceTechnician(
                    appliance_id=appliance.id,
                    technician_id=technician.id,
                    is_primary=False,
                )
            )
    service_record = ServiceRecord(appliance_id=appliance.id, **payload.model_dump())
    db.add(service_record)
    db.commit()
    db.refresh(service_record)
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return service_record
