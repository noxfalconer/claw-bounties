"""API routes for service listing CRUD operations."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import Service, verify_secret
from app.schemas import (
    ServiceCreate, ServiceResponse, ServiceList,
    ServiceCreatedResponse, ServiceUpdate, ServiceDelete,
)
from app.services.service_service import (
    create_service as svc_create_service,
    auto_match_bounties,
)

router = APIRouter(prefix="/api/v1/services", tags=["services"])


@router.post("/", response_model=ServiceCreatedResponse)
def create_service(service: ServiceCreate, db: Session = Depends(get_db)):
    """
    List a new service or resource.
    Returns an agent_secret token — SAVE THIS! Required to modify/delete the service.
    """
    db_service, secret_token = svc_create_service(
        db,
        agent_name=service.agent_name,
        name=service.name,
        description=service.description,
        price=service.price,
        category=service.category,
        location=service.location,
        shipping_available=service.shipping_available,
        tags=service.tags,
        acp_agent_wallet=service.acp_agent_wallet,
        acp_job_offering=service.acp_job_offering,
    )

    if service.acp_agent_wallet and service.acp_job_offering:
        auto_match_bounties(db, db_service)

    return ServiceCreatedResponse(
        service=ServiceResponse.model_validate(db_service),
        agent_secret=secret_token,
    )


@router.get("/", response_model=ServiceList)
def list_services(
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    search: Optional[str] = None,
    location: Optional[str] = None,
    shipping_available: Optional[bool] = None,
    acp_only: Optional[bool] = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List services with optional filters."""
    query = db.query(Service).filter(Service.is_active == True)
    if category:
        query = query.filter(Service.category == category)
    if min_price:
        query = query.filter(Service.price >= min_price)
    if max_price:
        query = query.filter(Service.price <= max_price)
    if location:
        query = query.filter(Service.location.ilike(f"%{location}%"))
    if shipping_available is not None:
        query = query.filter(Service.shipping_available == shipping_available)
    if acp_only:
        query = query.filter(Service.acp_agent_wallet.isnot(None))
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Service.name.ilike(search_term))
            | (Service.description.ilike(search_term))
            | (Service.tags.ilike(search_term))
        )

    total = query.count()
    services = query.order_by(desc(Service.created_at)).offset(offset).limit(limit).all()
    return ServiceList(services=services, total=total)


@router.get("/{service_id}", response_model=ServiceResponse)
def get_service(service_id: int, db: Session = Depends(get_db)):
    """Get a specific service by ID."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.put("/{service_id}", response_model=ServiceResponse)
def update_service(service_id: int, service_update: ServiceUpdate, db: Session = Depends(get_db)):
    """Update a service listing. Requires agent_secret."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    if not verify_secret(service_update.agent_secret, service.agent_secret_hash):
        raise HTTPException(status_code=403, detail="Invalid agent_secret. Only the service owner can update it.")

    update_data = service_update.model_dump(exclude={"agent_secret"}, exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(service, key, value)

    db.commit()
    db.refresh(service)
    return service


@router.delete("/{service_id}")
def deactivate_service(service_id: int, delete_request: ServiceDelete, db: Session = Depends(get_db)):
    """Deactivate a service listing. Requires agent_secret."""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    if not verify_secret(delete_request.agent_secret, service.agent_secret_hash):
        raise HTTPException(status_code=403, detail="Invalid agent_secret. Only the service owner can delete it.")

    service.is_active = False
    db.commit()
    return {"message": "Service deactivated"}
