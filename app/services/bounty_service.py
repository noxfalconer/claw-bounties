"""Shared business logic for bounty operations."""
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database import SessionLocal
from app.models import Bounty, BountyStatus, Service, generate_secret, verify_secret
from app.schemas import ACPSearchResult, ACPAgent
from app.utils import validate_callback_url, sanitize_text

logger = logging.getLogger(__name__)


# --------------- Webhook helpers ---------------

async def send_bounty_webhook(callback_url: str, event: str, bounty_data: dict) -> None:
    """Send webhook notification for bounty events."""
    if not callback_url:
        return
    if not validate_callback_url(callback_url):
        logger.warning(f"Blocked webhook to invalid/private URL: {callback_url}")
        return

    payload = {
        "event": event,
        "bounty": bounty_data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(callback_url, json=payload)
            logger.info(f"Webhook sent ({event}) to {callback_url}: {response.status_code}")
    except Exception as e:
        logger.error(f"Webhook failed for {callback_url}: {e}")


# --------------- ACP search ---------------

async def search_acp_registry(query: str) -> ACPSearchResult:
    """Search ACP registry using the in-memory cache."""
    try:
        from app.acp_registry import search_agents

        results = search_agents(query)
        if not results:
            return ACPSearchResult(found=False, agents=[], message="No matching services found on ACP")

        agents = [
            ACPAgent(
                wallet_address=a.get("wallet_address", ""),
                name=a.get("name", "Unknown"),
                description=a.get("description", ""),
                job_offerings=[j.get("name", "") for j in a.get("job_offerings", [])],
            )
            for a in results
        ]
        return ACPSearchResult(
            found=True, agents=agents, message=f"Found {len(agents)} matching service(s) on ACP"
        )
    except Exception as e:
        return ACPSearchResult(found=False, agents=[], message=f"ACP search error: {str(e)}")


# --------------- Bounty CRUD ---------------

def create_bounty(
    db: Session,
    *,
    poster_name: str,
    title: str,
    description: str,
    budget: float,
    category: str = "digital",
    requirements: Optional[str] = None,
    tags: Optional[str] = None,
    poster_callback_url: Optional[str] = None,
    set_expiry: bool = True,
) -> tuple[Bounty, str]:
    """
    Create a bounty in the DB.
    Returns (bounty, plaintext_secret).
    """
    secret_token, secret_hash = generate_secret()

    bounty = Bounty(
        poster_name=sanitize_text(poster_name),
        poster_callback_url=poster_callback_url,
        poster_secret_hash=secret_hash,
        title=sanitize_text(title),
        description=sanitize_text(description),
        requirements=sanitize_text(requirements) if requirements else None,
        budget=budget,
        category=category,
        tags=sanitize_text(tags) if tags else None,
        status=BountyStatus.OPEN,
        expires_at=datetime.utcnow() + timedelta(days=30) if set_expiry else None,
    )
    db.add(bounty)
    db.commit()
    db.refresh(bounty)
    return bounty, secret_token


def get_bounty_by_id(db: Session, bounty_id: int) -> Optional[Bounty]:
    """Get a bounty by ID or return None."""
    return db.query(Bounty).filter(Bounty.id == bounty_id).first()


def claim_bounty(
    db: Session,
    bounty: Bounty,
    claimer_name: str,
    claimer_callback_url: Optional[str] = None,
) -> str:
    """
    Claim a bounty. Returns the claimer_secret plaintext.
    Caller must check bounty.status == OPEN before calling.
    """
    secret_token, secret_hash = generate_secret()

    bounty.status = BountyStatus.CLAIMED
    bounty.claimed_by = sanitize_text(claimer_name)
    bounty.claimer_callback_url = claimer_callback_url
    bounty.claimer_secret_hash = secret_hash
    bounty.claimed_at = datetime.utcnow()
    db.commit()
    db.refresh(bounty)
    return secret_token


def fulfill_bounty(db: Session, bounty: Bounty, acp_job_id: Optional[str] = None) -> Bounty:
    """Mark a bounty as fulfilled."""
    bounty.status = BountyStatus.FULFILLED
    bounty.acp_job_id = acp_job_id
    bounty.fulfilled_at = datetime.utcnow()
    db.commit()
    db.refresh(bounty)
    return bounty


def cancel_bounty(db: Session, bounty: Bounty) -> Bounty:
    """Cancel a bounty."""
    bounty.status = BountyStatus.CANCELLED
    db.commit()
    db.refresh(bounty)
    return bounty


def get_platform_stats(db: Session) -> dict[str, int]:
    """Get bounty platform statistics."""
    return {
        "total_bounties": db.query(Bounty).count(),
        "open_bounties": db.query(Bounty).filter(Bounty.status == BountyStatus.OPEN).count(),
        "matched_bounties": db.query(Bounty).filter(Bounty.status == BountyStatus.MATCHED).count(),
        "fulfilled_bounties": db.query(Bounty).filter(Bounty.status == BountyStatus.FULFILLED).count(),
    }


def check_rate_limit(db: Session, poster_name: str, max_per_hour: int = 5) -> Optional[str]:
    """Check if a poster has exceeded the bounty creation rate limit. Returns error message or None."""
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_count = (
        db.query(Bounty)
        .filter(Bounty.poster_name == poster_name, Bounty.created_at >= one_hour_ago)
        .count()
    )
    if recent_count >= max_per_hour:
        return f"Rate limit exceeded: {poster_name} has created {recent_count} bounties in the last hour. Max {max_per_hour} per hour."
    return None
