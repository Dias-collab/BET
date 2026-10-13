from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright

from .config import Settings
from .notify import TelegramNotifier
from .olimp import OlimpBrowser
from .telegram_web import TelegramWebMonitor
from .vision import extract_coupon


LOG = logging.getLogger("bet_agent")


def _parse_clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


def _active(settings: Settings) -> bool:
    current = datetime.now(ZoneInfo(settings.timezone)).time()
    return _parse_clock(settings.active_from) <= current <= _parse_clock(settings.active_to)


async def run_setup(settings: Settings) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        for name, url in (
            ("telegram", settings.telegram_channel_url),
            ("olimp", settings.olimp_url),
        ):
            profile = settings.state_dir / name
            context = await pw.chromium.launch_persistent_context(
                str(profile),
                channel=settings.browser_channel,
                headless=False,
                viewport={"width": 1365, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            print(f"Войдите в {name} в открывшемся окне, затем нажмите Enter здес.")
            await asyncio.to_thread(input)
            await context.close()


async def process_once(settings: Settings) -> bool:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    async with async_playwright() as pw:
        telegram_context = await pw.chromium.launch_persistent_context(
            str(settings.state_dir / "telegram"),
            channel=settings.browser_channel,
            headless=settings.headless,
        )
        olimp_context = await pw.chromium.launch_persistent_context(
            str(settings.state_dir / "olimp"),
            channel=settings.browser_channel,
            headless=settings.headless,
        )
        try:
            monitor = TelegramWebMonitor(
                telegram_context,
                settings.telegram_channel_url,
                settings.telegram_post_prefix,
                settings.data_dir,
            )
            post = await monitor.latest()
            if post is None:
                return False
            coupon = await asyncio.to_thread(
                extract_coupon,
                post.image_path,
                base_url=settings.ollama_url,
                model=settings.ollama_model,
            )
            olimp = OlimpBrowser(olimp_context, settings.olimp_url)
            await olimp.open()
            if not await olimp.login_if_needed(settings.olimp_login, settings.olimp_password):
                notifier.send_text("❌ Olimpbet отклонил логин или пароль.")
                return False
            await olimp.build_coupon(coupon)
            proof = settings.data_dir / f"olimp-{post.post_id}.png"
            verification = await olimp.verify(coupon, proof)
            if verification.ok:
                notifier.send_photo(proof, f"✅ Купон собран и сверен\n{coupon.summary()}\nСтавка НЕ подтверждена.")
                monitor.mark_seen(post.post_id)
                return True
            notifier.send_photo(
                proof,
                "⚠️ Купон не прошёл сверку\n" + "\n".join(verification.problems),
            )
            return False
        finally:
            await telegram_context.close()
            await olimp_context.close()


async def run_forever(settings: Settings) -> None:
    while True:
        try:
            if _active(settings):
                await process_once(settings)
        except Exception:
            LOG.exception("Ошибка цикла агента")
        await asyncio.sleep(settings.poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "once", "run"), nargs="?", default="run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    if args.command == "setup":
        asyncio.run(run_setup(settings))
    elif args.command == "once":
        asyncio.run(process_once(settings))
    else:
        asyncio.run(run_forever(settings))


if __name__ == "__main__":
    main()
