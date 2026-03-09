"""Service balance status persistence."""

import logging

from src.database.connection import get_pool

logger = logging.getLogger(__name__)


async def get_balance_ok(service_name: str) -> bool:
    """Get persisted balance status for a service. Returns True if unknown."""
    pool = get_pool()
    row = await pool.fetchval(
        "SELECT balance_ok FROM service_status WHERE service_name = $1",
        service_name,
    )
    return row if row is not None else True


async def set_balance_ok(service_name: str, balance_ok: bool) -> None:
    """Persist balance status for a service (upsert)."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO service_status (service_name, balance_ok, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (service_name)
        DO UPDATE SET balance_ok = $2, updated_at = NOW()
        """,
        service_name, balance_ok,
    )


async def load_all_balance_states() -> dict[str, bool]:
    """Load all service balance states from DB."""
    pool = get_pool()
    rows = await pool.fetch("SELECT service_name, balance_ok FROM service_status")
    return {row["service_name"]: row["balance_ok"] for row in rows}
