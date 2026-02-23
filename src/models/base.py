"""
SQLAlchemy 2.0 async DeclarativeBase for TCG Radar.

All models inherit from this Base.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all TCG Radar database models."""
    pass
