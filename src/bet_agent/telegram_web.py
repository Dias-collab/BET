from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext, Page


@dataclass(frozen=True, slots=True)
class TelegramPost:
    post_id: str
    text: str
    image_path: Path


class TelegramWebMonitor:
    def __init__(self, context: BrowserContext, channel_url: str, prefix: str, data_dir: Path):
        self.context = context
        self.channel_url = channel_url
        self.prefix = prefix
        self.prefix_folded = prefix.casefold()
        self.data_dir = data_dir
        self.page: Page | None = None
        self.seen_path = data_dir / "seen_posts.json"

    def _seen(self) -> set[str]:
        if not self.seen_path.exists():
            return set()
        return set(json.loads(self.seen_path.read_text(encoding="utf-8")))

    def mark_seen(self, post_id: str) -> None:
        seen = self._seen()
        seen.add(post_id)
        self.seen_path.parent.mkdir(parents=True, exist_ok=True)
        self.seen_path.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")

    async def open(self) -> None:
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto(self.channel_url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(1800)

    async def latest(self) -> TelegramPost | None:
        if self.page is None:
            await self.open()
        assert self.page is not None
        # Telegram K changes class suffixes often; message/data-mid are the stable anchors.
        messages = self.page.locator("[data-mid], .message").filter(has_text=self.prefix)
        if await messages.count() == 0:
            # Telegram sometimes ignores a direct numeric chat URL. Fall back to its global
            # post search, open the newest matching result, then inspect the actual message.
            search = self.page.locator("input.input-search-input").first
            if await search.count() == 0:
                return None
            await search.fill(self.prefix)
            await self.page.wait_for_timeout(2000)
            snippets = self.page.locator("span.dialog-subtitle-span-last").filter(
                has_text=self.prefix
            )
            if await snippets.count() == 0:
                return None
            await snippets.first.click()
            await self.page.wait_for_timeout(1800)
            messages = self.page.locator("[data-mid], .message").filter(has_text=self.prefix)
        seen = self._seen()
        for index in range(await messages.count() - 1, -1, -1):
            message = messages.nth(index)
            text = (await message.inner_text()).strip()
            if self.prefix_folded not in text.casefold():
                continue
            mid = await message.get_attribute("data-mid")
            post_id = mid or hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]
            if post_id in seen:
                continue
            media = message.locator("img.media-photo").last
            if await media.count() == 0:
                continue
            self.data_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.data_dir / f"telegram-{post_id}.png"
            # Screenshot the message media to support blob-backed Telegram images.
            await media.screenshot(path=str(image_path))
            return TelegramPost(post_id=post_id, text=text, image_path=image_path)
        return None
