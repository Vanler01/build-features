"""Process entry points.

    python3 -m hydration.main serve    # webhooks + reminder loop (deployed)
    python3 -m hydration.main poll     # long polling + reminder loop (local)
    python3 -m hydration.main seed     # load the drink catalog

Both run modes share the same ``Dispatcher``, so nothing below the transport
knows which one is in use.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

import httpx

from . import handlers
from .adapters.line import LineAdapter
from .adapters.telegram import TelegramAdapter
from .ai import parse as parse_mod
from .ai import vision as vision_mod
from .api.app import WebhookConfig, create_app
from .api.dispatch import Dispatcher
from .api.polling import poll_forever
from .config import ConfigError, Settings, optional
from .core import db, seed
from .core.models import Platform
from .scheduler import runner

_LOG = logging.getLogger(__name__)


def build_dispatcher(
    settings: Settings, client: httpx.AsyncClient
) -> Dispatcher:
    """Wire adapters and handler dependencies from configuration.

    A platform with no token is simply absent, so a single-platform deployment
    does not need the other one's secrets.
    """
    adapters: dict[Platform, object] = {}
    if settings.telegram_bot_token:
        adapters[Platform.TELEGRAM] = TelegramAdapter(settings.telegram_bot_token, client)
    if settings.line_channel_access_token:
        adapters[Platform.LINE] = LineAdapter(settings.line_channel_access_token, client)
    if not adapters:
        raise SystemExit(
            "No messaging platform configured. Set TELEGRAM_BOT_TOKEN and/or "
            "LINE_CHANNEL_ACCESS_TOKEN in .env — see .env.example."
        )

    anthropic_client = parse_mod.build_client(settings.anthropic_api_key)

    def parse(text: str) -> object:
        return parse_mod.parse_drink_message(
            anthropic_client, text, model=settings.parse_model,
            max_tokens=settings.parse_max_tokens,
        )

    def parse_photo(image: bytes, caption: str | None) -> object:
        return vision_mod.parse_drink_photo(
            anthropic_client, image, caption=caption, model=settings.parse_model,
            max_tokens=settings.parse_max_tokens,
        )

    deps = handlers.HandlerDeps(
        parse=parse,  # type: ignore[arg-type]
        link_base_url=settings.link_base_url,
        parse_photo=parse_photo,  # type: ignore[arg-type]
        # Photo download is per-platform, so it is resolved at dispatch time
        # rather than bound here.
        fetch_photo=None,
    )
    return Dispatcher(adapters, deps)  # type: ignore[arg-type]


async def _serve(settings: Settings) -> None:
    import uvicorn

    async with httpx.AsyncClient() as client:
        dispatcher = build_dispatcher(settings, client)
        app = create_app(
            dispatcher,
            WebhookConfig(
                db_path=settings.db_path,
                telegram_secret=optional("TELEGRAM_WEBHOOK_SECRET"),
                line_channel_secret=settings.line_channel_secret,
            ),
        )
        conn = db.open_database(settings.db_path)
        reminder_task = asyncio.create_task(
            runner.run_forever(conn, dispatcher.adapters)
        )
        config = uvicorn.Config(
            app, host=optional("HOST", "0.0.0.0"), port=int(optional("PORT", "8000")),
            log_level="info",
        )
        try:
            await uvicorn.Server(config).serve()
        finally:
            reminder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminder_task
            conn.close()


async def _poll(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("Polling is Telegram-only; set TELEGRAM_BOT_TOKEN.")

    async with httpx.AsyncClient() as client:
        dispatcher = build_dispatcher(settings, client)
        conn = db.open_database(settings.db_path)
        reminder_task = asyncio.create_task(
            runner.run_forever(conn, dispatcher.adapters)
        )
        try:
            await poll_forever(conn, dispatcher, settings.telegram_bot_token, client)
        finally:
            reminder_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reminder_task
            conn.close()


def _seed(db_path: str) -> None:
    """Load the drink catalog.

    Takes a path rather than Settings because seeding needs no API key at all,
    and demanding one to load a JSON file would be a pointless barrier.
    """
    conn = db.open_database(db_path)
    report = seed.load_into(conn)
    print(f"Loaded {report.loaded} drinks; {report.with_nutrition} have nutrition.")
    if not report.complete:
        print(f"{len(report.awaiting_sourcing)} still need sourcing:")
        for drink_id in report.awaiting_sourcing:
            print(f"  {drink_id}")
        print("\nRun tools/source_catalog.py, then hydration-drink-data-validator.")
    conn.close()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the chosen mode."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("serve", "poll", "seed"))
    args = parser.parse_args(argv)

    if args.mode == "seed":
        _seed(optional("HYDRATION_DB_PATH", "./hydration.sqlite3"))
        return 0

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        # A missing key is a setup problem, not a crash. Say what is missing
        # and stop, rather than printing a traceback at someone who has not
        # created their .env yet.
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        asyncio.run(_serve(settings) if args.mode == "serve" else _poll(settings))
    except KeyboardInterrupt:
        _LOG.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
