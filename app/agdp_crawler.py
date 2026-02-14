"""aGDP leaderboard crawler — fetches data from Virtuals Protocol API."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.database import SessionLocal
from app.models import AgdpAgent, AgdpEpoch

logger = logging.getLogger(__name__)

BASE_URL = "https://api.virtuals.io"
MAX_RETRIES = 3
BACKOFF_BASE = 2.0
TOP_N_REWARDS = 20  # only fetch estimated rewards for top N agents


async def _fetch(client: httpx.AsyncClient, path: str, params: dict | None = None) -> Any:
    """Fetch with retry logic."""
    url = f"{BASE_URL}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt == MAX_RETRIES:
                logger.error("Failed %s after %d attempts: %s", url, MAX_RETRIES, e)
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning("Retry %d/%d for %s: %s (wait %.1fs)", attempt, MAX_RETRIES, url, e, wait)
            await asyncio.sleep(wait)


async def crawl() -> None:
    """Run a full aGDP crawl cycle."""
    logger.info("aGDP crawl started")
    async with httpx.AsyncClient() as client:
        # 1. Fetch epochs
        try:
            epochs_data = await _fetch(client, "/api/agdp-leaderboard-epochs", {"sort": "epochNumber:desc"})
        except Exception:
            logger.exception("Failed to fetch epochs, aborting crawl")
            return

        epochs = epochs_data.get("data", epochs_data) if isinstance(epochs_data, dict) else epochs_data
        if not epochs:
            logger.warning("No epochs returned")
            return

        db = SessionLocal()
        try:
            # 2. Upsert epochs
            for ep in epochs:
                attrs = ep.get("attributes", ep)  # handle Strapi-style or flat
                epoch_id = ep.get("id") or attrs.get("id")
                epoch_num = attrs.get("epochNumber")
                if not epoch_id:
                    continue

                existing = db.query(AgdpEpoch).filter(AgdpEpoch.id == epoch_id).first()
                vals = dict(
                    epoch_number=epoch_num,
                    starts_at=attrs.get("startsAt"),
                    ends_at=attrs.get("endsAt"),
                    status=attrs.get("status"),
                    usdc_snapshot=attrs.get("usdcSnapshotOfEpochStartDay", 0),
                    cbbtc_snapshot=attrs.get("cbbtcSnapshotOfEpochStartDay", 0),
                )
                if existing:
                    for k, v in vals.items():
                        setattr(existing, k, v)
                else:
                    db.add(AgdpEpoch(id=epoch_id, **vals))

            db.commit()
            logger.info("Upserted %d epochs", len(epochs))

            # 3. For the latest epoch, fetch ranking + prize pool
            latest = epochs[0]
            latest_attrs = latest.get("attributes", latest)
            latest_id = latest.get("id") or latest_attrs.get("id")

            # Prize pool
            try:
                pool = await _fetch(client, f"/api/agdp-leaderboard-epochs/{latest_id}/prize-pool")
                pool_data = pool.get("data", pool) if isinstance(pool, dict) else pool
                ep_row = db.query(AgdpEpoch).filter(AgdpEpoch.id == latest_id).first()
                if ep_row and pool_data:
                    ep_row.prize_pool_total = pool_data.get("totalUsdcInPrizePool")
                    ep_row.prize_pool_usdc = pool_data.get("usdcBalance")
                    ep_row.prize_pool_cbbtc_balance = pool_data.get("cbbtcBalance")
                    db.commit()
                    logger.info("Updated prize pool for epoch %s", latest_id)
            except Exception:
                logger.exception("Failed to fetch prize pool for epoch %s", latest_id)

            # Ranking
            try:
                ranking_resp = await _fetch(
                    client,
                    f"/api/agdp-leaderboard-epochs/{latest_id}/ranking",
                    {"pagination[pageSize]": 1000},
                )
                agents_list = ranking_resp.get("data", ranking_resp) if isinstance(ranking_resp, dict) else ranking_resp
                if not isinstance(agents_list, list):
                    agents_list = []
            except Exception:
                logger.exception("Failed to fetch ranking for epoch %s", latest_id)
                agents_list = []

            # 4. Estimated rewards for top N
            rewards_map: dict[int, float] = {}
            for agent in agents_list[:TOP_N_REWARDS]:
                aid = agent.get("agentId") or agent.get("agent_id")
                if not aid:
                    continue
                try:
                    rew = await _fetch(
                        client,
                        f"/api/agdp-leaderboard-epochs/{latest_id}/estimated-rewards-distribution",
                        {"agentId": aid},
                    )
                    rew_data = rew.get("data", rew) if isinstance(rew, dict) else rew
                    if isinstance(rew_data, dict):
                        seller = rew_data.get("sellerDistribution", {})
                        rewards_map[aid] = seller.get("amount", 0) if isinstance(seller, dict) else 0
                except Exception:
                    logger.warning("Failed to fetch rewards for agent %s", aid)
                    await asyncio.sleep(0.5)

            # 5. Insert agent snapshots
            now = datetime.now(timezone.utc)
            for agent in agents_list:
                aid = agent.get("agentId")
                virtual = agent.get("virtual", {}) or {}
                db.add(AgdpAgent(
                    agent_id=aid,
                    epoch_id=latest_id,
                    agent_name=agent.get("agentName", ""),
                    agent_wallet_address=agent.get("agentWalletAddress", ""),
                    token_address=agent.get("tokenAddress"),
                    profile_pic=agent.get("profilePic"),
                    tag=agent.get("tag"),
                    category=agent.get("category"),
                    role=agent.get("role"),
                    symbol=agent.get("symbol"),
                    twitter_handle=agent.get("twitterHandle"),
                    has_graduated=agent.get("hasGraduated", False),
                    rating=agent.get("rating"),
                    success_rate=agent.get("successRate"),
                    successful_job_count=agent.get("successfulJobCount", 0),
                    unique_buyer_count=agent.get("uniqueBuyerCount", 0),
                    is_virtual_agent=agent.get("isVirtualAgent", False),
                    virtual_agent_id=str(agent.get("virtualAgentId")) if agent.get("virtualAgentId") else None,
                    total_revenue=agent.get("totalRevenue", 0),
                    owner_address=agent.get("ownerAddress"),
                    rank=agent.get("rank"),
                    prize_pool_percentage=agent.get("prizePoolPercentage"),
                    estimated_reward=rewards_map.get(aid),
                    mcap_in_virtual=virtual.get("mcapInVirtual"),
                    holder_count=virtual.get("holderCount"),
                    volume_24h=virtual.get("volume24h"),
                    total_value_locked=str(virtual.get("totalValueLocked")) if virtual.get("totalValueLocked") else None,
                    snapshot_at=now,
                ))

            db.commit()
            logger.info("Inserted %d agent snapshots for epoch %s", len(agents_list), latest_id)

        except Exception:
            db.rollback()
            logger.exception("aGDP crawl failed")
        finally:
            db.close()

    logger.info("aGDP crawl completed")


async def agdp_crawler_loop() -> None:
    """Background loop: crawl every hour."""
    while True:
        try:
            await crawl()
        except Exception:
            logger.exception("aGDP crawler loop error")
        await asyncio.sleep(3600)
