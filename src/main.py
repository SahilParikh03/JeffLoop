"""
TCG Radar — Application Entrypoint

Initializes async SQLAlchemy engine, configures structlog, and starts the scheduler.

Run via:
    python -m src.main
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import settings
from src.pipeline.scheduler import run_scheduler


# ---------------------------------------------------------------------------
# Structlog Configuration
# ---------------------------------------------------------------------------


def _configure_logging(log_level: str = "INFO") -> None:
    """
    Set up structured logging with JSON output.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
    """
    # Configure stdlib logging first (for third-party libraries)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )

    # Configure structlog with JSON output
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------


async def create_db_engine() -> tuple[Any, async_sessionmaker[AsyncSession]]:
    """
    Create SQLAlchemy async engine and session factory.

    The DATABASE_URL is read from settings (env variable DATABASE_URL).
    Uses asyncpg for async Postgres connections.

    Returns:
        (engine, session_factory) tuple.
    """
    logger = structlog.get_logger(__name__)

    logger.info("database_engine_initializing", database_url=settings.DATABASE_URL)

    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,  # Set to True if you want SQL logging
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before use
    )

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    logger.info("database_engine_ready")
    return engine, session_factory


# ---------------------------------------------------------------------------
# Application Startup
# ---------------------------------------------------------------------------


async def main() -> None:
    """
    Application entrypoint. Initializes subsystems and starts the scheduler.

    Execution order:
    1. Configure logging (structlog JSON)
    2. Create async database engine and session factory
    3. Verify database connection (health check)
    4. Start the scheduler (run indefinitely until shutdown signal)
    """
    # Configure logging first
    _configure_logging(log_level="INFO")
    logger = structlog.get_logger(__name__)

    logger.info("tcg_radar_startup_begin", version="0.1.0", date="2026-02-22")

    # Validate critical config
    if not settings.JUSTTCG_API_KEY:
        logger.warning("config_justtcg_api_key_missing", note="using empty API key")
    if not settings.POKEMONTCG_API_KEY:
        logger.warning("config_pokemontcg_api_key_missing", note="using empty API key")

    # Create database engine and session factory
    try:
        engine, session_factory = await create_db_engine()
    except Exception as e:
        logger.error(
            "database_engine_creation_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

    # Health check: verify database connection
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        logger.info("database_health_check_passed")
    except Exception as e:
        logger.error(
            "database_health_check_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        await engine.dispose()
        raise

    logger.info(
        "tcg_radar_startup_complete",
        customs_regime=settings.CUSTOMS_REGIME.value,
        layer_3_scraping_enabled=settings.ENABLE_LAYER_3_SCRAPING,
        layer_35_social_enabled=settings.ENABLE_LAYER_35_SOCIAL,
    )

    # Run the scheduler (blocks until shutdown)
    try:
        await run_scheduler(engine, session_factory)
    except KeyboardInterrupt:
        logger.info("tcg_radar_interrupted_by_user")
    except Exception as e:
        logger.error(
            "tcg_radar_fatal_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
    finally:
        # Cleanup
        await engine.dispose()
        logger.info("tcg_radar_shutdown_complete")


# ---------------------------------------------------------------------------
# CLI Entry
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    asyncio.run(main())
