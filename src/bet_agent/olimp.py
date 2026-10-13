from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

from playwright.async_api import BrowserContext, Locator, Page

from .models import Coupon, CouponBuildResult, CouponVerification


class OlimpError(RuntimeError):
    pass


class EventNotFound(OlimpError):
    pass


class MarketNotFound(OlimpError):
    pass


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    value = re.sub(r"[^\w.+()-]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _decimal_from_text(value: str) -> Decimal | None:
    matches = re.findall(r"\d+(?:[.,]\d+)?", value)
    if not matches:
        return None
    try:
        # Main outcome tabs include labels such as P1/P2 before the actual odd.
        return Decimal(matches[-1].replace(",", "."))
    except InvalidOperation:
        return None


class OlimpBrowser:
    """Build a verified coupon. There is intentionally no bet-submit method."""

    def __init__(self, context: BrowserContext, base_url: str):
        self.context = context
        self.base_url = base_url
        self.page: Page | None = None

    async def open(self) -> None:
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto(self.base_url, wait_until="domcontentloaded")
        await self._wait_for_app()

    async def _wait_for_app(self, timeout_ms: int = 20_000) -> None:
        assert self.page is not None
        await self.page.get_by_placeholder(re.compile("поиск", re.I)).first.wait_for(
            state="visible", timeout=timeout_ms
        )

    async def ensure_logged_in(self) -> bool:
        assert self.page is not None
        return await self.page.get_by_role(
            "button", name=re.compile(r"^\s*вход\s*$", re.I)
        ).count() == 0

    async def login_if_needed(self, login: str | None, password: str | None) -> bool:
        assert self.page is not None
        login_button = self.page.get_by_role(
            "button", name=re.compile(r"^\s*вход\s*$", re.I)
        ).first
        if await login_button.count() == 0:
            return True
        if not login or not password:
            return False

        await login_button.click()
        auth_frame = None
        for _ in range(20):
            auth_frame = next(
                (frame for frame in self.page.frames if "auth.olimpbet.kz/ui-light/login" in frame.url),
                None,
            )
            if auth_frame is not None:
                break
            await self.page.wait_for_timeout(100)
        if auth_frame is None:
            raise OlimpError("Форма входа Olimpbet не загрузилась")

        phone_digits = re.sub(r"\D", "", login)
        is_phone = len(phone_digits) in {10, 11} and login.replace("+", "").replace(" ", "").isdigit()
        if not is_phone:
            await auth_frame.locator("[data-testid='sigh-in-segment-login']").click()
        login_input = auth_frame.locator(
            "input[name='phone']" if is_phone else "[data-testid='sign-in-login-input']"
        ).last
        password_input = auth_frame.locator("[data-testid='sign-in-password-input']").last
        await login_input.fill(login)
        await password_input.fill(password)
        submit = auth_frame.get_by_role("button", name=re.compile("войти", re.I)).last
        await submit.evaluate("(element) => element.click()")

        for _ in range(30):
            if await self.ensure_logged_in():
                return True
            await self.page.wait_for_timeout(200)
        return False

    async def build_coupon(self, coupon: Coupon) -> CouponBuildResult:
        assert self.page is not None
        await self.clear_coupon()
        event_url = await self._open_event(coupon)
        selection = await self._locate_selection(coupon)
        odd = _decimal_from_text(await selection.inner_text())
        selected = (await selection.get_attribute("aria-selected")) == "true"
        if not selected:
            # The fixed coupon sidebar can overlap market tabs. A DOM click is
            # deterministic here and avoids Playwright waiting on that overlay.
            await selection.evaluate("(element) => element.click()")
            for _ in range(20):
                if (await selection.get_attribute("aria-selected")) == "true":
                    selected = True
                    break
                await self.page.wait_for_timeout(100)
        if not selected:
            raise MarketNotFound("Исход найден, но Olimpbet не добавил его в купон")
        return CouponBuildResult(event_url=event_url, current_odds=odd)

    async def clear_coupon(self) -> None:
        """Remove stale selections so every run produces exactly one coupon item."""
        assert self.page is not None
        counter = self.page.locator("[data-testid='basket-open-modal-button-outcomes-counter']")
        if await counter.count() == 0 or (await counter.inner_text()).strip() in {"", "0"}:
            return
        opener = self.page.locator("[data-testid='basket-open-modal-button']")
        if await opener.count():
            await opener.click()
            await self.page.wait_for_timeout(200)
        clear = self.page.locator("[data-testid='basket-clear-button']")
        if await clear.count() == 0:
            clear = self.page.locator("[data-testid='basket-portal-clear-button']")
        if await clear.count() == 0:
            raise OlimpError("Не удалось очистить старый купон")
        await clear.evaluate("(element) => element.click()")
        for _ in range(20):
            if await counter.count() == 0 or (await counter.inner_text()).strip() in {"", "0"}:
                return
            await self.page.wait_for_timeout(100)
        raise OlimpError("Старый купон не очистился")

    async def _open_event(self, coupon: Coupon) -> str:
        assert self.page is not None
        if not self.page.url.rstrip("/").startswith(self.base_url.rstrip("/")):
            await self.page.goto(self.base_url, wait_until="domcontentloaded")
            await self._wait_for_app()

        # Reuse an already open matching event. Besides being faster, this avoids
        # reopening the global search overlay on repeated autonomous runs.
        home_banner = self.page.locator("[data-testid='event-entire-banner-home-competitor']")
        away_banner = self.page.locator("[data-testid='event-entire-banner-away-competitor']")
        if await home_banner.count() and await away_banner.count():
            current_home = normalize_text(await home_banner.inner_text())
            current_away = normalize_text(await away_banner.inner_text())
            expected = (normalize_text(coupon.home_team), normalize_text(coupon.away_team))
            if (current_home, current_away) in {expected, expected[::-1]}:
                return self.page.url

        search = self.page.get_by_placeholder(re.compile("поиск", re.I)).first
        await search.fill(f"{coupon.home_team} {coupon.away_team}")
        candidates = self.page.locator("[data-testid^='search-overlay-events-event-competitors-']")
        try:
            await candidates.first.wait_for(state="visible", timeout=6_000)
        except Exception as exc:
            raise EventNotFound(f"Матч не найден: {coupon.event}") from exc
        expected = normalize_text(f"{coupon.home_team} - {coupon.away_team}")
        reverse = normalize_text(f"{coupon.away_team} - {coupon.home_team}")
        matches: list[Locator] = []
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if normalize_text(await candidate.inner_text()) in {expected, reverse}:
                matches.append(candidate)
        if not matches:
            raise EventNotFound(f"Матч не найден: {coupon.event}")

        chosen = await self._choose_event(matches, coupon)
        link = chosen.locator("xpath=ancestor::a[1]")
        href = await link.get_attribute("href")
        if not href:
            raise EventNotFound(f"Ссылка матча не найдена: {coupon.event}")
        await link.click()
        await self.page.wait_for_url(re.compile(r"/line/"), timeout=15_000)
        await self.page.get_by_text(re.compile(re.escape(coupon.home_team), re.I)).first.wait_for(
            state="visible", timeout=15_000
        )
        return self.page.url

    async def _choose_event(self, matches: list[Locator], coupon: Coupon) -> Locator:
        if len(matches) == 1 or not (coupon.event_date or coupon.event_time):
            return matches[0]
        for candidate in matches:
            text = normalize_text(await candidate.locator("xpath=ancestor::a[1]").inner_text())
            date_ok = not coupon.event_date or normalize_text(coupon.event_date) in text
            time_ok = not coupon.event_time or coupon.event_time in text
            if date_ok and time_ok:
                return candidate
        raise EventNotFound(f"Найдено несколько матчей, но не совпало время: {coupon.event}")

    async def _locate_selection(self, coupon: Coupon) -> Locator:
        if coupon.market == "both_teams_to_score":
            yes = normalize_text(coupon.selection) in {"yes", "да", "оз да"}
            return await self._market_option(
                re.compile(r"^обе\s+забьют$", re.I),
                0 if yes else 1,
                coupon,
            )

        if coupon.market == "total":
            number = self._selection_number(coupon.selection)
            over = any(word in normalize_text(coupon.selection) for word in ("over", "больше", "тб"))
            return await self._market_option(
                re.compile(rf"^тотал\s*\({re.escape(number)}\)$", re.I),
                0 if over else 1,
                coupon,
            )

        if coupon.market == "match_result":
            key = self._result_key(coupon.selection)
            testid = {"П1": "w1", "X": "wx", "П2": "w2"}[key]
            return await self._hot_probability(testid, coupon)

        if coupon.market == "double_chance":
            key = normalize_text(coupon.selection).upper().replace(" ", "")
            aliases = {"1X": "w1x", "1Х": "w1x", "12": "w12", "X2": "wx2", "Х2": "wx2"}
            if key not in aliases:
                raise MarketNotFound(f"Неизвестный двойной шанс: {coupon.selection}")
            return await self._hot_probability(aliases[key], coupon)

        if coupon.market == "handicap":
            team, value = self._handicap_parts(coupon)
            numeric = re.escape(value.rstrip("0").rstrip("."))
            if "." not in value or value.endswith(".0"):
                numeric += r"(?:\.0)?"
            return await self._category_tab(
                re.compile(r"^фора$", re.I),
                re.compile(rf"^{re.escape(team)}\s*\({numeric}\)", re.I),
                coupon,
            )

        return await self._direct_tab(
            re.compile("|".join(map(re.escape, self._selection_labels(coupon))), re.I), coupon
        )

    async def _market_option(
        self, pattern: re.Pattern[str], option_index: int, coupon: Coupon
    ) -> Locator:
        assert self.page is not None
        labels = self.page.get_by_text(pattern, exact=True)
        try:
            await labels.first.wait_for(state="visible", timeout=10_000)
        except Exception as exc:
            raise MarketNotFound(f"Рынок не найден: {pattern.pattern}") from exc
        for index in range(await labels.count()):
            label_cell = labels.nth(index).locator("xpath=parent::*")
            option = label_cell.locator(
                f"xpath=following-sibling::*[{option_index + 1}]//*[@role='tab']"
            )
            if await option.count() and await option.get_attribute("aria-disabled") != "true":
                return option.first
        raise MarketNotFound(f"Рынок не найден: {pattern.pattern}")

    async def _hot_probability(self, suffix: str, coupon: Coupon) -> Locator:
        """Select a full-match outcome from Olimp's pinned main-market strip."""
        assert self.page is not None
        tab = self.page.locator(
            f"[data-testid='event-entire-line-hot-probability-{suffix}'][role='tab']"
        ).first
        try:
            await tab.wait_for(state="visible", timeout=10_000)
        except Exception as exc:
            raise MarketNotFound(
                f"Основной исход матча не найден: {coupon.market} / {coupon.selection}"
            ) from exc
        if await tab.get_attribute("aria-disabled") == "true":
            raise MarketNotFound(
                f"Основной исход матча недоступен: {coupon.market} / {coupon.selection}"
            )
        return tab

    async def _category_tab(
        self, category_pattern: re.Pattern[str], outcome_pattern: re.Pattern[str], coupon: Coupon
    ) -> Locator:
        """Find an outcome only inside a named full-match market category."""
        assert self.page is not None
        titles = self.page.locator("[data-testid^='event-entire-category-title-']").filter(
            has_text=category_pattern
        )
        for index in range(await titles.count()):
            title = titles.nth(index)
            if not category_pattern.fullmatch((await title.inner_text()).strip()):
                continue
            panel = title.locator("xpath=ancestor::*[starts-with(@data-testid, 'event-entire-category-panel-')][1]")
            tabs = panel.locator("[role='tab']").filter(has_text=outcome_pattern)
            for tab_index in range(await tabs.count()):
                tab = tabs.nth(tab_index)
                if outcome_pattern.search((await tab.inner_text()).strip()) and await tab.get_attribute("aria-disabled") != "true":
                    return tab
        raise MarketNotFound(f"Исход не найден: {coupon.market} / {coupon.selection}")

    async def _direct_tab(self, pattern: re.Pattern[str], coupon: Coupon) -> Locator:
        assert self.page is not None
        labels = self.page.get_by_text(pattern, exact=True)
        try:
            await labels.first.wait_for(state="visible", timeout=10_000)
        except Exception as exc:
            raise MarketNotFound(f"Исход не найден: {coupon.market} / {coupon.selection}") from exc
        for index in range(await labels.count()):
            tab = labels.nth(index).locator("xpath=ancestor-or-self::*[@role='tab'][1]")
            if await tab.count() and await tab.get_attribute("aria-disabled") != "true":
                return tab
        raise MarketNotFound(f"Исход не найден: {coupon.market} / {coupon.selection}")

    @staticmethod
    def _selection_number(selection: str) -> str:
        match = re.search(r"\d+(?:[.,]\d+)?", selection)
        if not match:
            raise MarketNotFound(f"В тотале нет числа: {selection}")
        return match.group(0).replace(",", ".")

    @staticmethod
    def _result_key(selection: str) -> str:
        value = normalize_text(selection).replace(" ", "")
        mapping = {
            "home": "П1", "1": "П1", "п1": "П1",
            "draw": "X", "x": "X", "ничья": "X",
            "away": "П2", "2": "П2", "п2": "П2",
        }
        if value not in mapping:
            raise MarketNotFound(f"Неизвестный исход матча: {selection}")
        return mapping[value]

    @staticmethod
    def _handicap_parts(coupon: Coupon) -> tuple[str, str]:
        raw = normalize_text(coupon.selection.replace(",", "."))
        match = re.search(r"(?<!\d)([+-]\s*\d+(?:[.,]\d+)?)", raw)
        if not match:
            raise MarketNotFound(f"В форе нет значения со знаком: {coupon.selection}")
        value = match.group(1).replace(" ", "").replace(",", ".")
        home = normalize_text(coupon.home_team)
        away = normalize_text(coupon.away_team)
        if home in raw or re.search(r"\b(?:home|ф1|п1)\b", raw):
            return coupon.home_team, value
        if away in raw or re.search(r"\b(?:away|ф2|п2)\b", raw):
            return coupon.away_team, value
        raise MarketNotFound(f"В форе не указана команда: {coupon.selection}")

    @staticmethod
    def _selection_labels(coupon: Coupon) -> tuple[str, ...]:
        if coupon.market == "both_teams_to_score":
            return ("Обе забьют", "Да")
        if coupon.market == "total":
            number = OlimpBrowser._selection_number(coupon.selection)
            direction = "Больше" if "over" in normalize_text(coupon.selection) else "Меньше"
            return ("Тотал", number, direction)
        return (coupon.selection,)

    async def verify(self, coupon: Coupon, screenshot_path: Path) -> CouponVerification:
        assert self.page is not None
        coupon_tab = self.page.locator("[data-testid='basket-tab-coupon']")
        if await coupon_tab.count():
            await coupon_tab.click()
            await self.page.wait_for_timeout(400)
        body = " ".join((await self.page.locator("body").inner_text()).split())
        index = normalize_text(body).rfind("купон")
        coupon_text = body[index:] if index >= 0 else ""
        await self.page.screenshot(path=str(screenshot_path), full_page=False)

        actual = normalize_text(coupon_text)
        missing: list[str] = []
        for team in (coupon.home_team, coupon.away_team):
            if normalize_text(team) not in actual:
                missing.append(f"команда {team}")
        if coupon.market == "both_teams_to_score":
            if "обе забьют" not in actual:
                missing.append("исход Обе забьют")
            expected_yes = normalize_text(coupon.selection) in {"yes", "да", "оз да"}
            answer = "да" if expected_yes else "нет"
            if not re.search(rf"\b{answer}\b", actual):
                missing.append(f"исход {answer}")
        elif coupon.market == "total":
            number = self._selection_number(coupon.selection)
            if "тотал" not in actual or number not in actual:
                missing.append(f"исход Тотал {number}")
            over = any(word in normalize_text(coupon.selection) for word in ("over", "больше", "тб"))
            direction = r"(?:\bб\b|больше|\bтб\b)" if over else r"(?:\bм\b|меньше|\bтм\b)"
            if not re.search(direction, actual):
                missing.append("исход больше" if over else "исход меньше")
        elif coupon.market == "match_result":
            key = normalize_text(self._result_key(coupon.selection))
            if "1-й тайм" in actual or "2-й тайм" in actual:
                missing.append("выбран исход тайма вместо исхода матча")
            expected_label = {
                "п1": normalize_text(coupon.home_team),
                "x": "ничья",
                "п2": normalize_text(coupon.away_team),
            }[key]
            if "исход матча" not in actual or expected_label not in actual:
                missing.append(f"исход {key} ({expected_label})")
        elif coupon.market == "double_chance":
            key = normalize_text(coupon.selection).replace(" ", "").replace("х", "x")
            if "1-й тайм" in actual or "2-й тайм" in actual:
                missing.append("выбран двойной шанс тайма вместо матча")
            expected_label = {
                "1x": f"{normalize_text(coupon.home_team)} не проиграет",
                "12": "ничь",  # Olimp wording varies: «ничьи не будет» / «ничьей не будет».
                "x2": f"{normalize_text(coupon.away_team)} не проиграет",
            }.get(key)
            if not expected_label or "двойной шанс" not in actual or expected_label not in actual:
                missing.append(f"исход {key}")
        elif coupon.market == "handicap":
            team, value = self._handicap_parts(coupon)
            if "1-й тайм" in actual or "2-й тайм" in actual:
                missing.append("выбрана фора тайма вместо матча")
            normalized_value = value.rstrip("0").rstrip(".")
            if "фора" not in actual or normalize_text(team) not in actual or normalized_value not in actual:
                missing.append(f"фора {team} {value}")
        elif normalize_text(coupon.selection) not in actual:
            missing.append(f"исход {coupon.selection}")
        if re.search(r"купон\s+пуст", actual):
            missing.append("купон пуст")
        return CouponVerification(
            ok=not missing,
            expected=coupon,
            coupon_text=coupon_text,
            problems=tuple(f"В купоне не найдено: {item}" for item in missing),
        )
