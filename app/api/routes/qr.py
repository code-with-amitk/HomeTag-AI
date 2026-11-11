"""
> Why: Issue and revoke tags and serve anonymous, allowlisted appliance pages.
> Throughput: QR reads are cache-aside; tag writes require household authorization.
> Dependencies: FastAPI, SQLAlchemy, Redis, Jinja2 templates, and QR gateway service.
"""

import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.api.dependencies import AuthenticatedUser, DbSession
from app.api.schemas import QRTagCreate, QRTagRead, QRTagUpdate
from app.db.models import Appliance, ApplianceStatus, HouseholdMembership, Property, QRTag
from app.services.qr_gateway import get_public_view, invalidate_appliance_qr_cache

router = APIRouter(prefix="/v1", tags=["public QR"])
template_environment = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parents[2] / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


def _read_tag(
    db: Session,
    user_id: UUID,
    tag_id: str,
) -> tuple[QRTag, Appliance]:
    """Resolve a tag only if its owner belongs to the caller's active household."""
    result = db.execute(
        select(QRTag, Appliance)
        .join(Appliance, Appliance.id == QRTag.appliance_id)
        .join(Property, Property.id == Appliance.property_id)
        .join(HouseholdMembership, HouseholdMembership.household_id == Property.household_id)
        .where(
            QRTag.tag_id == tag_id,
            HouseholdMembership.user_id == user_id,
            HouseholdMembership.is_active.is_(True),
        )
    ).first()
    if result is None:
        raise _not_found()
    tag, appliance = result
    return tag, appliance


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "not_found", "message": "Resource not found."},
    )


def _tag_read(tag: QRTag) -> QRTagRead:
    return QRTagRead(
        tag_id=tag.tag_id,
        scan_path=f"/v1/scan/{tag.tag_id}",
        is_active=tag.is_active and tag.revoked_at is None,
        public_fields=tag.public_fields,
    )


@router.get(
    "/scan/{tag_id}",
    response_class=HTMLResponse,
    responses={404: {"description": "Tag not found or inactive."}},
    summary="View an appliance from its public QR tag",
)
def scan_tag(tag_id: str, request: Request, db: DbSession) -> Response:
    """Render a public HTML view without exposing unapproved appliance data."""
    public_view = get_public_view(db, request.app.state.redis, tag_id)
    if public_view is None:
        template = template_environment.get_template("qr_not_found.html")
        return HTMLResponse(
            template.render(),
            status_code=status.HTTP_404_NOT_FOUND,
            headers={"Cache-Control": "no-store"},
        )
    template = template_environment.get_template("qr_appliance.html")
    return HTMLResponse(
        template.render(appliance=public_view),
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/appliances/{appliance_id}/tags",
    response_model=QRTagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create or rotate an appliance QR tag",
)
def create_tag(
    appliance_id: UUID,
    payload: QRTagCreate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> QRTagRead:
    """Create an opaque tag and revoke any currently active tag for this appliance."""
    appliance = db.scalar(
        select(Appliance)
        .join(Property, Property.id == Appliance.property_id)
        .join(HouseholdMembership, HouseholdMembership.household_id == Property.household_id)
        .where(
            Appliance.id == appliance_id,
            Appliance.status == ApplianceStatus.ACTIVE.value,
            Property.archived_at.is_(None),
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    )
    if appliance is None:
        raise _not_found()

    now = datetime.now(timezone.utc)
    active_tags = db.scalars(
        select(QRTag).where(QRTag.appliance_id == appliance.id, QRTag.is_active.is_(True))
    ).all()
    for old_tag in active_tags:
        old_tag.is_active = False
        old_tag.revoked_at = now

    tag = QRTag(
        appliance_id=appliance.id,
        tag_id=secrets.token_urlsafe(32),
        is_active=True,
        public_fields=list(dict.fromkeys(payload.public_fields)),
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return _tag_read(tag)


@router.patch(
    "/tags/{tag_id}",
    response_model=QRTagRead,
    summary="Update an appliance QR tag's public fields",
)
def update_tag(
    tag_id: str,
    payload: QRTagUpdate,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> QRTagRead:
    """Replace the public allowlist on an active tag owned by the caller."""
    tag, appliance = _read_tag(db, user.id, tag_id)
    if not tag.is_active or tag.revoked_at is not None:
        raise _not_found()
    tag.public_fields = list(dict.fromkeys(payload.public_fields))
    db.commit()
    db.refresh(tag)
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return _tag_read(tag)


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Revoke an appliance QR tag",
)
def revoke_tag(
    tag_id: str,
    user: AuthenticatedUser,
    db: DbSession,
    request: Request,
) -> Response:
    """Revoke an active tag and immediately invalidate its cached public view."""
    tag, appliance = _read_tag(db, user.id, tag_id)
    if not tag.is_active or tag.revoked_at is not None:
        raise _not_found()
    tag.is_active = False
    tag.revoked_at = datetime.now(timezone.utc)
    db.commit()
    invalidate_appliance_qr_cache(db, request.app.state.redis, appliance.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
