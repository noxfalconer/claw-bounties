"""aGDP leaderboard API endpoints."""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AgdpAgent, AgdpEpoch

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/agdp", tags=["agdp"])


def _latest_epoch(db: Session) -> Optional[AgdpEpoch]:
    return db.query(AgdpEpoch).order_by(desc(AgdpEpoch.epoch_number)).first()


def _leaderboard_for_epoch(db: Session, epoch_id: int) -> list[dict]:
    """Get latest snapshot per agent for a given epoch."""
    # Subquery: max snapshot_at per agent_id for this epoch
    sub = (
        db.query(AgdpAgent.agent_id, func.max(AgdpAgent.snapshot_at).label("max_snap"))
        .filter(AgdpAgent.epoch_id == epoch_id)
        .group_by(AgdpAgent.agent_id)
        .subquery()
    )
    agents = (
        db.query(AgdpAgent)
        .join(sub, (AgdpAgent.agent_id == sub.c.agent_id) & (AgdpAgent.snapshot_at == sub.c.max_snap))
        .filter(AgdpAgent.epoch_id == epoch_id)
        .order_by(AgdpAgent.rank.asc().nulls_last())
        .all()
    )
    return [_agent_dict(a) for a in agents]


def _agent_dict(a: AgdpAgent) -> dict:
    return {
        "agent_id": a.agent_id,
        "epoch_id": a.epoch_id,
        "agent_name": a.agent_name,
        "agent_wallet_address": a.agent_wallet_address,
        "token_address": a.token_address,
        "profile_pic": a.profile_pic,
        "tag": a.tag,
        "category": a.category,
        "role": a.role,
        "symbol": a.symbol,
        "twitter_handle": a.twitter_handle,
        "has_graduated": a.has_graduated,
        "rating": a.rating,
        "success_rate": a.success_rate,
        "successful_job_count": a.successful_job_count,
        "unique_buyer_count": a.unique_buyer_count,
        "is_virtual_agent": a.is_virtual_agent,
        "total_revenue": a.total_revenue,
        "owner_address": a.owner_address,
        "rank": a.rank,
        "prize_pool_percentage": a.prize_pool_percentage,
        "estimated_reward": a.estimated_reward,
        "mcap_in_virtual": a.mcap_in_virtual,
        "holder_count": a.holder_count,
        "volume_24h": a.volume_24h,
        "snapshot_at": a.snapshot_at.isoformat() if a.snapshot_at else None,
    }


@router.get("/leaderboard", summary="Current epoch leaderboard")
async def leaderboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    epoch = _latest_epoch(db)
    if not epoch:
        return {"data": [], "epoch": None}
    agents = _leaderboard_for_epoch(db, epoch.id)
    return {
        "data": agents,
        "epoch": {
            "id": epoch.id,
            "epoch_number": epoch.epoch_number,
            "status": epoch.status,
            "starts_at": epoch.starts_at.isoformat() if epoch.starts_at else None,
            "ends_at": epoch.ends_at.isoformat() if epoch.ends_at else None,
            "prize_pool_total": epoch.prize_pool_total,
        },
        "count": len(agents),
    }


@router.get("/leaderboard/{epoch_id}", summary="Leaderboard for specific epoch")
async def leaderboard_by_epoch(epoch_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    epoch = db.query(AgdpEpoch).filter(AgdpEpoch.id == epoch_id).first()
    if not epoch:
        return {"data": [], "epoch": None, "error": "Epoch not found"}
    agents = _leaderboard_for_epoch(db, epoch_id)
    return {
        "data": agents,
        "epoch": {
            "id": epoch.id,
            "epoch_number": epoch.epoch_number,
            "status": epoch.status,
            "prize_pool_total": epoch.prize_pool_total,
        },
        "count": len(agents),
    }


@router.get("/agents/{agent_id}", summary="Agent detail")
async def agent_detail(agent_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    latest = (
        db.query(AgdpAgent)
        .filter(AgdpAgent.agent_id == agent_id)
        .order_by(desc(AgdpAgent.snapshot_at))
        .first()
    )
    if not latest:
        return {"data": None, "error": "Agent not found"}
    return {"data": _agent_dict(latest)}


@router.get("/agents/{agent_id}/history", summary="Agent revenue history")
async def agent_history(
    agent_id: int,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        db.query(AgdpAgent)
        .filter(AgdpAgent.agent_id == agent_id)
        .order_by(desc(AgdpAgent.snapshot_at))
        .limit(limit)
        .all()
    )
    return {
        "agent_id": agent_id,
        "snapshots": [
            {
                "epoch_id": r.epoch_id,
                "rank": r.rank,
                "total_revenue": r.total_revenue,
                "successful_job_count": r.successful_job_count,
                "unique_buyer_count": r.unique_buyer_count,
                "rating": r.rating,
                "success_rate": r.success_rate,
                "snapshot_at": r.snapshot_at.isoformat() if r.snapshot_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/stats", summary="aGDP summary stats")
async def agdp_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    epoch = _latest_epoch(db)
    if not epoch:
        return {"epoch": None, "total_agents": 0, "total_revenue": 0, "prize_pool": None}

    # Use latest snapshot per agent
    sub = (
        db.query(AgdpAgent.agent_id, func.max(AgdpAgent.snapshot_at).label("max_snap"))
        .filter(AgdpAgent.epoch_id == epoch.id)
        .group_by(AgdpAgent.agent_id)
        .subquery()
    )
    stats = (
        db.query(
            func.count(AgdpAgent.id).label("total"),
            func.coalesce(func.sum(AgdpAgent.total_revenue), 0).label("revenue"),
        )
        .join(sub, (AgdpAgent.agent_id == sub.c.agent_id) & (AgdpAgent.snapshot_at == sub.c.max_snap))
        .filter(AgdpAgent.epoch_id == epoch.id)
        .first()
    )

    return {
        "epoch": {
            "id": epoch.id,
            "epoch_number": epoch.epoch_number,
            "status": epoch.status,
            "starts_at": epoch.starts_at.isoformat() if epoch.starts_at else None,
            "ends_at": epoch.ends_at.isoformat() if epoch.ends_at else None,
        },
        "total_agents": stats.total if stats else 0,
        "total_revenue": float(stats.revenue) if stats else 0,
        "prize_pool": {
            "total": epoch.prize_pool_total,
            "usdc": epoch.prize_pool_usdc,
            "cbbtc_balance": epoch.prize_pool_cbbtc_balance,
        } if epoch.prize_pool_total else None,
    }
