"""
> Why: Provide tenant-scoped property lifecycle endpoints.
> Throughput: CRUD operations use indexed household membership filters.
> Dependencies: FastAPI, Pydantic, SQLAlchemy, and tenant authorization helpers.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import select

from app.api.dependencies import AuthenticatedUser, DbSession, require_membership
from app.api.schemas import PropertyCreate, PropertyRead, PropertyUpdate
from app.db.models import HouseholdMembership, Property
from app.services.authorization import get_accessible_property
from app.services.qr_gateway import invalidate_property_qr_cache

router = APIRouter(prefix="/v1/properties", tags=["properties"])


@router.get("", response_model=list[PropertyRead], summary="List accessible properties")
def list_properties(
    user: AuthenticatedUser,
    db: DbSession,
    include_archived: bool = Query(default=False, description="Include archived properties."),
) -> list[Property]:
    """List properties belonging to the caller's active households."""
    query = (
        select(Property)
        .join(HouseholdMembership, HouseholdMembership.household_id == Property.household_id)
        .where(
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
        .order_by(Property.created_at, Property.id)
    )
    if not include_archived:
        query = query.where(Property.archived_at.is_(None))
    return list(db.scalars(query).all())


@router.post(
    "",
    response_model=PropertyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a property",
)
def create_property(
    payload: PropertyCreate,
    user: AuthenticatedUser,
    db: DbSession,
) -> Property:
    """Create a property only within a household the caller belongs to."""
    require_membership(db, user, payload.household_id)
    property_record = Property(**payload.model_dump())
    db.add(property_record)
    db.commit()
    db.refresh(property_record)
    return property_record


@router.get("/{property_id}", response_model=PropertyRead, summary="Read a property")
def read_property(
    property_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> Property:
    """Read an active property in an accessible household."""
    return get_accessible_property(db, user, property_id)


@router.patch("/{property_id}", response_model=PropertyRead, summary="Update a property")
def update_property(
    property_id: UUID,
    payload: PropertyUpdate,
    user: AuthenticatedUser,
    db: DbSession,
) -> Property:
    """Update an active property in an accessible household."""
    property_record = get_accessible_property(db, user, property_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_name", "message": "Property name cannot be null."},
        )
    for field, value in updates.items():
        setattr(property_record, field, value)
    db.commit()
    db.refresh(property_record)
    return property_record


@router.delete(
    "/{property_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Archive a property",
)
def archive_property(
    property_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Response:
    """Soft archive a property and preserve its appliance history."""
    property_record = get_accessible_property(db, user, property_id)
    property_record.archived_at = datetime.now(timezone.utc)
    db.commit()
    invalidate_property_qr_cache(db, request.app.state.redis, property_record.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
