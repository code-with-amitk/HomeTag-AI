"""
> Why: Centralize tenant-scoped lookups for household-owned inventory.
> Throughput: Uses indexed joins across membership, property, and appliance keys.
> Dependencies: SQLAlchemy entities and FastAPI's not-found response.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Appliance,
    HouseholdMembership,
    Property,
    ServiceRecord,
    Technician,
    User,
)


def not_found() -> HTTPException:
    """Return a non-disclosing not-found error for absent or inaccessible resources."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "not_found", "message": "Resource not found."},
    )


def get_accessible_property(db: Session, user: User, property_id: UUID) -> Property:
    """Resolve an active property within one of the user's active households."""
    property_record = db.scalar(
        select(Property)
        .join(
            HouseholdMembership,
            HouseholdMembership.household_id == Property.household_id,
        )
        .where(
            Property.id == property_id,
            Property.archived_at.is_(None),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    )
    if property_record is None:
        raise not_found()
    return property_record


def get_accessible_appliance(db: Session, user: User, appliance_id: UUID) -> Appliance:
    """Resolve an active appliance through its active property and membership."""
    appliance = db.scalar(
        select(Appliance)
        .join(Property, Property.id == Appliance.property_id)
        .join(
            HouseholdMembership,
            HouseholdMembership.household_id == Property.household_id,
        )
        .where(
            Appliance.id == appliance_id,
            Appliance.status == "active",
            Property.archived_at.is_(None),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    )
    if appliance is None:
        raise not_found()
    return appliance


def get_accessible_technician(
    db: Session,
    user: User,
    technician_id: UUID,
) -> Technician:
    """Resolve an active technician within an active household membership."""
    technician = db.scalar(
        select(Technician)
        .join(
            HouseholdMembership,
            HouseholdMembership.household_id == Technician.household_id,
        )
        .where(
            Technician.id == technician_id,
            Technician.is_active.is_(True),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    )
    if technician is None:
        raise not_found()
    return technician


def get_accessible_service_record(
    db: Session,
    user: User,
    service_record_id: UUID,
) -> ServiceRecord:
    """Resolve a service event through its appliance, property, and membership."""
    record = db.scalar(
        select(ServiceRecord)
        .join(Appliance, Appliance.id == ServiceRecord.appliance_id)
        .join(Property, Property.id == Appliance.property_id)
        .join(
            HouseholdMembership,
            HouseholdMembership.household_id == Property.household_id,
        )
        .where(
            ServiceRecord.id == service_record_id,
            Appliance.status == "active",
            Property.archived_at.is_(None),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    )
    if record is None:
        raise not_found()
    return record
