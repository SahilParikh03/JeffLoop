"""
TCG Radar — Admin User Registration Script

Creates a users row + user_profiles row (1:1 extension pattern) for a new subscriber.
Run this for each beta user during manual onboarding (per spec: no self-serve registration in Phase 1).

Usage:
    python scripts/add_user.py --telegram-chat-id 123456789 --country US --tier trader
    python scripts/add_user.py --telegram-chat-id 111 --country DE --tier free --discord-channel-id 987654321
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Resolve project root so this script can be run from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src.models.user import User
from src.models.user_profile import UserProfile

VALID_TIERS = {"free", "trader", "pro", "shop"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new TCG Radar subscriber (users + user_profiles rows).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/add_user.py --telegram-chat-id 123456789 --country US --tier trader
  python scripts/add_user.py --telegram-chat-id 111 --country DE --tier free
  python scripts/add_user.py --telegram-chat-id 222 --country UK --tier pro --discord-channel-id 987654321
""",
    )
    parser.add_argument(
        "--telegram-chat-id",
        type=int,
        required=True,
        help="Telegram chat ID for signal delivery (get via @userinfobot on Telegram).",
    )
    parser.add_argument(
        "--country",
        type=str,
        required=True,
        help="ISO country code (e.g., US, DE, UK). Controls fee schedules and customs.",
    )
    parser.add_argument(
        "--tier",
        type=str,
        default="free",
        choices=sorted(VALID_TIERS),
        help="Subscription tier: free | trader | pro | shop (default: free).",
    )
    parser.add_argument(
        "--discord-channel-id",
        type=int,
        default=None,
        help="Optional Discord channel ID for Phase 2 Discord delivery.",
    )
    return parser.parse_args()


async def create_user(
    telegram_chat_id: int,
    country: str,
    tier: str,
    discord_channel_id: int | None,
) -> uuid.UUID:
    """
    Insert a users row and a matching user_profiles row with the same UUID.

    The 1:1 extension pattern requires users to be inserted first (FK parent),
    then user_profiles with the same UUID as PK (FK child).
    """
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    user_id = uuid.uuid4()

    async with session_factory() as session:
        user = User(id=user_id)
        session.add(user)
        await session.flush()  # Write users row before profile FK references it

        profile = UserProfile(
            id=user_id,
            telegram_chat_id=telegram_chat_id,
            country=country.upper(),
            subscription_tier=tier,
            discord_channel_id=discord_channel_id,
        )
        session.add(profile)
        await session.commit()

    await engine.dispose()
    return user_id


async def main() -> None:
    args = parse_args()

    print(
        f"Creating user: telegram_chat_id={args.telegram_chat_id}, "
        f"country={args.country.upper()}, tier={args.tier}"
    )

    try:
        user_id = await create_user(
            telegram_chat_id=args.telegram_chat_id,
            country=args.country,
            tier=args.tier,
            discord_channel_id=args.discord_channel_id,
        )
        print(f"User created successfully.")
        print(f"  users.id           = {user_id}")
        print(f"  user_profiles.id   = {user_id}")
        print(f"  telegram_chat_id   = {args.telegram_chat_id}")
        print(f"  country            = {args.country.upper()}")
        print(f"  subscription_tier  = {args.tier}")
        if args.discord_channel_id:
            print(f"  discord_channel_id = {args.discord_channel_id}")
        print()
        print(
            "The scheduler will begin delivering signals to this user on the next scan."
        )
    except Exception as e:
        print(f"Failed to create user: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
