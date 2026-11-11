"""
> Why: Build privacy-limited QR views and maintain their bounded Redis cache.
> Throughput: Cache-aside reads with a short TTL and explicit write invalidation.
> Dependencies: SQLAlchemy, Redis, and QR/inventory persistence models.
"""

import json
import logging
from collections.abc import Sequence
from datetime import date
from typing import Protocol, cast
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Appliance,
    ApplianceStatus,
    ApplianceTechnician,
    Property,
    QRTag,
    ServiceRecord,
    Technician,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30
CACHE_KEY_PREFIX = "hometag:qr:v1:"
PUBLIC_SERVICE_HISTORY_LIMIT = 10
PUBLIC_SERVICE_DESCRIPTION_LIMIT = 500


class QRCache(Protocol):
    """Redis operations used by the public QR cache."""

    def get(self, key: str) -> str | None: ...

    def setex(self, key: str, seconds: int, value: str) -> object: ...

    def delete(self, *keys: str) -> int: ...


def _build_public_view(db: Session, tag_id: str) -> dict[str, object] | None:
    """Return only owner-approved appliance fields and explicitly public history."""
    tag = db.scalar(select(QRTag).where(QRTag.tag_id == tag_id, QRTag.is_active.is_(True)))
    if tag is None or tag.revoked_at is not None:
        return None

    appliance = db.get(Appliance, tag.appliance_id)
    if appliance is None or appliance.status != ApplianceStatus.ACTIVE.value:
        return None
    property_record = db.get(Property, appliance.property_id)
    if property_record is None or property_record.archived_at is not None:
        return None

    allowed = set(tag.public_fields)
    public_view: dict[str, object] = {}
    for field in ("name", "make", "model", "warranty_expiry"):
        if field in allowed:
            value = getattr(appliance, field)
            public_view[field] = value.isoformat() if isinstance(value, date) else value

    if "technician_contact" in allowed:
        technician = db.scalar(
            select(Technician)
            .join(
                ApplianceTechnician,
                ApplianceTechnician.technician_id == Technician.id,
            )
            .where(
                ApplianceTechnician.appliance_id == appliance.id,
                Technician.is_active.is_(True),
            )
            .order_by(ApplianceTechnician.is_primary.desc(), Technician.name, Technician.id)
            .limit(1)
        )
        if technician is not None:
            public_view["technician_contact"] = {
                "name": technician.name,
                "organization": technician.organization,
                "phone": technician.phone,
                "email": technician.email,
            }

    if "service_history" in allowed:
        records = db.scalars(
            select(ServiceRecord)
            .where(
                ServiceRecord.appliance_id == appliance.id,
                ServiceRecord.is_public.is_(True),
            )
            .order_by(ServiceRecord.serviced_at.desc(), ServiceRecord.id)
            .limit(PUBLIC_SERVICE_HISTORY_LIMIT)
        ).all()
        public_view["service_history"] = [
            {
                "serviced_at": record.serviced_at.isoformat(),
                "description": (
                    record.description[: PUBLIC_SERVICE_DESCRIPTION_LIMIT - 3] + "..."
                    if len(record.description) > PUBLIC_SERVICE_DESCRIPTION_LIMIT
                    else record.description
                ),
            }
            for record in records
        ]

    return public_view


def get_public_view(
    db: Session,
    redis: QRCache,
    tag_id: str,
) -> dict[str, object] | None:
    """Fetch a public view from Redis or build and cache its database projection."""
    cache_key = f"{CACHE_KEY_PREFIX}{tag_id}"
    try:
        cached = redis.get(cache_key)
    except RedisError:
        logger.exception("QR cache read failed; falling back to PostgreSQL")
        cached = None

    if cached is not None:
        try:
            decoded = json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            logger.error("Discarding malformed QR cache entry")
            try:
                redis.delete(cache_key)
            except RedisError:
                logger.exception("Unable to remove malformed QR cache entry")
        else:
            if isinstance(decoded, dict):
                return cast(dict[str, object], decoded)
            logger.error("Discarding QR cache entry with an invalid shape")
            try:
                redis.delete(cache_key)
            except RedisError:
                logger.exception("Unable to remove malformed QR cache entry")

    public_view = _build_public_view(db, tag_id)
    if public_view is not None:
        try:
            redis.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(public_view))
        except RedisError:
            logger.exception("QR cache write failed; serving the database projection")
    return public_view


def invalidate_appliance_qr_cache(db: Session, redis: QRCache, appliance_id: UUID) -> None:
    """Invalidate every cached tag projection associated with an appliance."""
    tag_ids = db.scalars(select(QRTag.tag_id).where(QRTag.appliance_id == appliance_id)).all()
    _delete_cache_keys(redis, tag_ids)


def invalidate_property_qr_cache(db: Session, redis: QRCache, property_id: UUID) -> None:
    """Invalidate public projections when a property is archived."""
    appliance_ids = db.scalars(
        select(Appliance.id).where(Appliance.property_id == property_id)
    ).all()
    for appliance_id in appliance_ids:
        invalidate_appliance_qr_cache(db, redis, appliance_id)


def invalidate_technician_qr_cache(db: Session, redis: QRCache, technician_id: UUID) -> None:
    """Invalidate projections that may include a changed technician contact."""
    appliance_ids = db.scalars(
        select(ApplianceTechnician.appliance_id).where(
            ApplianceTechnician.technician_id == technician_id
        )
    ).all()
    for appliance_id in appliance_ids:
        invalidate_appliance_qr_cache(db, redis, appliance_id)


def _delete_cache_keys(redis: QRCache, tag_ids: Sequence[str]) -> None:
    """Delete tag cache entries and report failures for bounded-TTL recovery."""
    if not tag_ids:
        return
    keys = [f"{CACHE_KEY_PREFIX}{tag_id}" for tag_id in tag_ids]
    try:
        redis.delete(*keys)
    except RedisError:
        logger.exception(
            "QR cache invalidation failed; entries expire within %s seconds",
            CACHE_TTL_SECONDS,
        )
