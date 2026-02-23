"""
TCG Radar — Synergy Detection (Section 11)

Builds and queries a co-occurrence matrix from tournament decklists.
When a card spikes, its synergy partners are pre-loaded for monitoring.

"Support card detection" — if Charizard ex spikes, automatically flag
Rare Candy, Professor's Research, etc. based on co-occurrence frequency.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.limitless import DecklistEntry

logger = structlog.get_logger(__name__)


class SynergyTarget(BaseModel):
    """A card identified as a synergy partner."""

    card_name: str
    card_id: str | None = None
    cooccurrence_count: int = 0


def build_cooccurrence_matrix(
    decklists: list[list[DecklistEntry]],
) -> dict[tuple[str, str], int]:
    """
    Build a co-occurrence matrix from multiple decklists.

    For each pair of cards that appear in the same decklist,
    increment their co-occurrence count.

    Args:
        decklists: List of decklists, each a list of DecklistEntry.

    Returns:
        Dict mapping (card_a, card_b) -> count. Keys are always
        lexicographically sorted so (A, B) and (B, A) are the same entry.
    """
    matrix: dict[tuple[str, str], int] = defaultdict(int)

    for decklist in decklists:
        card_names = sorted(set(entry.card_name for entry in decklist if entry.card_name))

        for i in range(len(card_names)):
            for j in range(i + 1, len(card_names)):
                pair = (card_names[i], card_names[j])
                matrix[pair] += 1

    return dict(matrix)


def get_synergy_targets(
    card_name: str,
    matrix: dict[tuple[str, str], int],
    top_n: int = 20,
) -> list[SynergyTarget]:
    """
    Find the top N synergy partners for a given card.

    Searches the co-occurrence matrix for all pairs involving
    the target card, sorted by frequency.

    Args:
        card_name: Card to find synergies for.
        matrix: Co-occurrence matrix from build_cooccurrence_matrix().
        top_n: Maximum number of results.

    Returns:
        List of SynergyTarget sorted by cooccurrence_count descending.
    """
    partners: list[SynergyTarget] = []

    for (card_a, card_b), count in matrix.items():
        if card_a == card_name:
            partners.append(SynergyTarget(card_name=card_b, cooccurrence_count=count))
        elif card_b == card_name:
            partners.append(SynergyTarget(card_name=card_a, cooccurrence_count=count))

    partners.sort(key=lambda t: t.cooccurrence_count, reverse=True)
    return partners[:top_n]


async def store_cooccurrence_matrix(
    matrix: dict[tuple[str, str], int],
    session: AsyncSession,
) -> int:
    """
    Persist co-occurrence matrix to the synergy_cooccurrence table.

    Uses upsert to increment counts on conflict.

    Args:
        matrix: Co-occurrence matrix to store.
        session: Async database session.

    Returns:
        Number of rows upserted.
    """
    count = 0

    for (card_a, card_b), cooccurrence in matrix.items():
        try:
            stmt = text("""
                INSERT INTO synergy_cooccurrence (card_a, card_b, count, last_updated)
                VALUES (:card_a, :card_b, :count, CURRENT_TIMESTAMP)
                ON CONFLICT (card_a, card_b) DO UPDATE SET
                    count = synergy_cooccurrence.count + EXCLUDED.count,
                    last_updated = CURRENT_TIMESTAMP
            """)
            await session.execute(stmt, {
                "card_a": card_a,
                "card_b": card_b,
                "count": cooccurrence,
            })
            count += 1
        except Exception as e:
            logger.error(
                "synergy_store_error",
                card_a=card_a,
                card_b=card_b,
                error=str(e),
                source="synergy",
            )

    await session.commit()

    logger.info(
        "synergy_matrix_stored",
        pairs_stored=count,
        source="synergy",
    )
    return count


async def load_synergy_targets(
    card_name: str,
    session: AsyncSession,
    top_n: int = 20,
) -> list[SynergyTarget]:
    """
    Load top synergy partners from the database.

    Queries the synergy_cooccurrence table for all pairs involving
    the target card, ordered by count descending.
    """
    stmt = text("""
        SELECT card_a, card_b, count FROM synergy_cooccurrence
        WHERE card_a = :card_name OR card_b = :card_name
        ORDER BY count DESC
        LIMIT :top_n
    """)

    result = await session.execute(stmt, {"card_name": card_name, "top_n": top_n})
    rows = result.fetchall()

    targets: list[SynergyTarget] = []
    for row in rows:
        partner = row[1] if row[0] == card_name else row[0]
        targets.append(SynergyTarget(
            card_name=partner,
            cooccurrence_count=row[2],
        ))

    return targets
