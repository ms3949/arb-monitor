"""
Extract and validate Kalshi ticker and Polymarket slug from their respective URLs.

Consistent extraction rules:
  Kalshi:     Last path segment, uppercased → event_ticker (e.g. KXNCAAMBGAME-26FEB14NMSUJVST)
  Polymarket: Last path segment as-is → slug (e.g. cbb-nmxst-jaxst-2026-02-14)

URL patterns:
  Kalshi:     https://kalshi.com/markets/{series}/{category}/{event_ticker}
  Polymarket: https://polymarket.com/sports/{sport}/games/week/{n}/{slug}
              https://polymarket.com/event/{slug}

Usage:
  from url_to_ticker import parse_kalshi_url, parse_polymarket_url, validate_pair

  kalshi_url = "https://kalshi.com/markets/kxncaambgame/mens-college-basketball-mens-game/kxncaambgame-26feb14nmsujvst"
  poly_url   = "https://polymarket.com/sports/cbb/games/week/1/cbb-nmxst-jaxst-2026-02-14"

  result = validate_pair(kalshi_url, poly_url)
  # result.kalshi_event_ticker, result.kalshi_markets, result.poly_slug, result.poly_market, ...
"""

import json
import os
import re
import requests
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOLT_API = "https://spro.agency/api"


# --- URL parsing ---

def _last_path_segment(url: str) -> Optional[str]:
    """Extract the last non-empty path segment from a URL."""
    if not url or not url.strip():
        return None
    parsed = urlparse(url.strip())
    path = (parsed.path or "").rstrip("/")
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else None


def parse_kalshi_url(url: str) -> Optional[str]:
    """
    Extract event ticker from a Kalshi market URL.

    Example:
      https://kalshi.com/markets/kxncaambgame/mens-college-basketball-mens-game/kxncaambgame-26feb14nmsujvst
      -> KXNCAAMBGAME-26FEB14NMSUJVST

    Returns uppercase ticker (Kalshi API uses uppercase).
    """
    segment = _last_path_segment(url)
    if not segment:
        return None
    return segment.upper()


def parse_polymarket_url(url: str) -> Optional[str]:
    """
    Extract slug from a Polymarket URL.

    Examples:
      https://polymarket.com/sports/cbb/games/week/1/cbb-nmxst-jaxst-2026-02-14
      -> cbb-nmxst-jaxst-2026-02-14

      https://polymarket.com/event/super-bowl-champion-2026-731
      -> super-bowl-champion-2026-731

    Returns slug as-is (Gamma API accepts lowercase slugs).
    """
    return _last_path_segment(url)


# --- Validation ---

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA_API = "https://gamma-api.polymarket.com"


def validate_kalshi_ticker(event_ticker: str) -> tuple[bool, list[dict], str]:
    """
    Validate Kalshi event ticker via API.

    Kalshi uses event_ticker for the game; individual markets have tickers like
    KXNCAAMBGAME-26FEB14NMSUJVST-NMSU (with team suffix).

    Returns:
      (valid, markets_list, error_message)
    """
    if not event_ticker or not event_ticker.strip():
        return False, [], "Empty ticker"

    ticker = event_ticker.strip().upper()
    url = f"{KALSHI_API}/markets"
    params = {"event_ticker": ticker, "limit": 50}

    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return False, [], f"API error {r.status_code}: {r.text[:200]}"

        data = r.json()
        markets = data.get("markets") or []
        if not markets:
            return False, [], f"No markets found for event_ticker={ticker}"

        active = [m for m in markets if m.get("status") in ("open", "active")]
        if not active:
            return False, markets, f"Event exists but no open/active markets for {ticker}"

        return True, active, ""
    except requests.RequestException as e:
        return False, [], str(e)


def validate_polymarket_slug(slug: str) -> tuple[bool, Optional[dict], str]:
    """
    Validate Polymarket slug via Gamma API.

    Tries markets?slug= first (returns moneyline for CBB), then events?slug=.

    Returns:
      (valid, market_or_event_data, error_message)
    """
    if not slug or not slug.strip():
        return False, None, "Empty slug"

    s = slug.strip()
    for endpoint, param in [("markets", "slug"), ("events", "slug")]:
        url = f"{GAMMA_API}/{endpoint}"
        params = {param: s}
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                if endpoint == "markets":
                    if item.get("active", True) and not item.get("closed", False):
                        return True, item, ""
                else:
                    mkts = item.get("markets") or []
                    active_mkts = [m for m in mkts if m.get("active", True) and not m.get("closed", False)]
                    if active_mkts:
                        return True, item, ""
            elif isinstance(data, dict) and data.get("id"):
                return True, data, ""
        except requests.RequestException:
            continue

    return False, None, f"No active market/event found for slug={s}"


# --- Bolt API validation ---

def _parse_date_from_slug(slug: str) -> Optional[str]:
    """Extract YYYY-MM-DD from slug like cbb-smho-kenest-2026-02-14."""
    if not slug:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", slug)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _parse_date_from_kalshi_ticker(ticker: str) -> Optional[str]:
    """Extract YYYY-MM-DD from ticker like KXNCAAMBGAME-26FEB14SHSUKENN."""
    if not ticker:
        return None
    m = re.search(r"(\d{2})([A-Z]{3})(\d{2})", ticker, re.IGNORECASE)
    if m:
        day, mon, yr = m.group(1), m.group(2).upper(), m.group(3)
        months = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
                  "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}
        mm = months.get(mon)
        if mm:
            return f"20{yr}-{mm}-{day}"
    return None


def fetch_bolt_teams(
    bolt_key: str,
    game_date: str,
    team_a: str,
    team_b: str,
    sport: str = "NCAAB",
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetch Bolt get_games and find the matching game. Returns exact home_team, away_team from Bolt API.

    Returns (bolt_home, bolt_away, bolt_game_string) or (None, None, None) if not found.
    """
    if not bolt_key or not game_date or not team_a or not team_b:
        return None, None, None
    try:
        r = requests.get(f"{BOLT_API}/get_games", params={"key": bolt_key}, timeout=15)
        if r.status_code != 200:
            return None, None, None
        games = r.json()
        if not isinstance(games, dict):
            return None, None, None
        # Build search terms from team names; also use poly-style names (e.g. "Texas-Rio Grande Valley Vaqueros")
        def terms(name: str) -> list[str]:
            return [t.lower() for t in re.split(r"[\s\-]+", name) if len(t) > 1 and t.lower() not in ("f", "st", "vs")]

        a_terms = terms(team_a)
        b_terms = terms(team_b)

        def game_matches(game_str: str, info: dict) -> bool:
            if info.get("sport") not in (sport, "NCAA Basketball", "Basketball"):
                return False
            if game_date not in game_str:
                return False
            # Match against game string and orig_teams (Bolt may use different display names)
            searchable = game_str.lower()
            if info.get("orig_teams"):
                searchable += " " + str(info.get("orig_teams", "")).lower()
            a_ok = any(t in searchable for t in a_terms)
            b_ok = any(t in searchable for t in b_terms)
            return a_ok and b_ok
        for game_str, info in games.items():
            if not isinstance(info, dict):
                continue
            if game_matches(game_str, info):
                # Parse "Home vs Away, date, id"
                parts = game_str.split(",")[0].strip()
                if " vs " in parts:
                    home, away = parts.split(" vs ", 1)
                    return home.strip(), away.strip(), game_str
        return None, None, None
    except Exception:
        return None, None, None


# --- Bolt team extraction (fallback when API not available) ---

def _parse_kalshi_home_away(kalshi_markets: list) -> tuple[Optional[str], Optional[str]]:
    """
    Parse home/away from Kalshi market title. Format: "X at Y" => Y is home, X is away.
    Returns (home, away) or (None, None).
    """
    if not kalshi_markets:
        return None, None
    title = (kalshi_markets[0].get("title") or "").strip()
    # "New Mexico St. at Jacksonville St. Winner?" -> away at home
    m = re.search(r"(.+?)\s+at\s+(.+?)(?:\s+Winner|\s*$)", title, re.IGNORECASE | re.DOTALL)
    if m:
        away_raw, home_raw = m.group(1).strip(), m.group(2).strip()
        return home_raw, away_raw
    return None, None


def _extract_poly_teams(poly_data: dict) -> list[dict]:
    """Extract team list from Polymarket event or market. Each item: {name, abbreviation}."""
    teams = []
    if isinstance(poly_data, dict):
        # Event has teams directly; market may have events[0].teams
        team_list = poly_data.get("teams")
        if not team_list and poly_data.get("events"):
            ev = poly_data["events"][0] if isinstance(poly_data["events"], list) else poly_data["events"]
            team_list = ev.get("teams") if isinstance(ev, dict) else None
        if team_list:
            for t in team_list:
                if isinstance(t, dict) and t.get("name"):
                    teams.append({"name": t["name"], "abbreviation": t.get("abbreviation", "")})
        elif "outcomes" in poly_data:
            raw = poly_data["outcomes"]
            outcomes = json.loads(raw) if isinstance(raw, str) else raw
            for o in (outcomes or []):
                if isinstance(o, str) and o not in ("Over", "Under", "Yes", "No"):
                    teams.append({"name": o, "abbreviation": ""})
    return teams


def _normalize_team_name(name: str) -> str:
    """Normalize for matching: 'New Mexico St.' <-> 'New Mexico State Aggies'."""
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r"\bSt\.?\s*$", "State", s, flags=re.IGNORECASE)
    return s


def _build_aliases(name: str, abbreviation: str, kalshi_suffix: Optional[str] = None) -> list[str]:
    """Build common aliases for Bolt matching."""
    aliases = []
    if name:
        aliases.append(name)
        # Without mascot (e.g. "New Mexico State" from "New Mexico State Aggies")
        parts = name.split()
        if len(parts) >= 2 and parts[-1] not in ("State", "St", "St."):
            aliases.append(" ".join(parts[:-1]))
        if "State" in name:
            aliases.append(name.replace(" State", " St.").replace(" State ", " St. "))
    if abbreviation:
        aliases.append(abbreviation.upper())
    if kalshi_suffix:
        aliases.append(kalshi_suffix)
    return list(dict.fromkeys(a for a in aliases if a))


def _extract_bolt_teams(
    kalshi_markets: list,
    poly_data: Optional[dict],
) -> tuple[Optional[str], Optional[str], list, list]:
    """
    Extract bolt_home, bolt_away, bolt_home_aliases, bolt_away_aliases.

    Uses Kalshi "X at Y" for home/away (Y=home); otherwise Polymarket teams order.
    Returns (bolt_home, bolt_away, home_aliases, away_aliases).
    """
    kalshi_home_raw, kalshi_away_raw = _parse_kalshi_home_away(kalshi_markets)
    poly_teams = _extract_poly_teams(poly_data) if poly_data else []

    def find_poly_name_for_kalshi(kalshi_name: str) -> Optional[str]:
        if not kalshi_name or not poly_teams:
            return None
        kn = _normalize_team_name(kalshi_name).lower()
        for t in poly_teams:
            pn = (t.get("name") or "").lower()
            pn_norm = _normalize_team_name(pn).lower()
            if kn in pn or pn in kn or kn in pn_norm or pn_norm in kn:
                return t.get("name")
        return None

    if kalshi_home_raw and kalshi_away_raw and poly_teams:
        home_name = find_poly_name_for_kalshi(kalshi_home_raw) or kalshi_home_raw
        away_name = find_poly_name_for_kalshi(kalshi_away_raw) or kalshi_away_raw
    elif len(poly_teams) >= 2:
        home_name = poly_teams[0].get("name")
        away_name = poly_teams[1].get("name")
    else:
        return None, None, [], []

    def get_abbr_and_suffix(name: str) -> tuple[str, Optional[str]]:
        abbr, suffix = "", None
        for t in poly_teams:
            if name and (t.get("name") or "").lower() in name.lower() or name.lower() in (t.get("name") or "").lower():
                abbr = t.get("abbreviation", "")
                break
        # Match Kalshi ticker suffix via subtitle (e.g. "New Mexico St." -> NMSU)
        for m in (kalshi_markets or []):
            ticker = m.get("ticker", "")
            if "-" not in ticker:
                continue
            s = ticker.split("-")[-1]
            sub = (m.get("yes_sub_title") or m.get("no_sub_title") or "").strip()
            if sub and name and find_poly_name_for_kalshi(sub) == name:
                suffix = s
                break
        return abbr, suffix

    home_abbr, home_suffix = get_abbr_and_suffix(home_name)
    away_abbr, away_suffix = get_abbr_and_suffix(away_name)
    home_aliases = _build_aliases(home_name, home_abbr, home_suffix)
    away_aliases = _build_aliases(away_name, away_abbr, away_suffix)

    return home_name, away_name, home_aliases, away_aliases


# --- Combined result ---

@dataclass
class UrlValidationResult:
    kalshi_event_ticker: Optional[str] = None
    kalshi_markets: list = field(default_factory=list)
    kalshi_valid: bool = False
    kalshi_error: str = ""

    poly_slug: Optional[str] = None
    poly_market: Optional[dict] = None
    poly_valid: bool = False
    poly_error: str = ""

    def to_config_snippet(
        self,
        team_ticker: Optional[str] = None,
        bolt_key: Optional[str] = None,
    ) -> dict:
        """
        Produce a config snippet for latency_logger / execution_bot.

        For Kalshi, if team_ticker is provided (e.g. NMSU, JVST), use that market.
        Otherwise use the first moneyline-style market.
        Includes bolt_home, bolt_away, bolt_home_aliases, bolt_away_aliases for Bolt feed matching.
        When bolt_key is set, validates against Bolt get_games API for exact team names.
        """
        out = {}
        if self.kalshi_valid and self.kalshi_markets:
            if team_ticker:
                ticker_upper = team_ticker.strip().upper()
                # Match by suffix (e.g. -NMSU, -SHSU) to avoid matching event part (SHSU in SHSUKENN)
                match = next(
                    (m for m in self.kalshi_markets
                     if (m.get("ticker") or "").endswith(f"-{ticker_upper}")),
                    None,
                )
                if match:
                    out["kalshi_market_ticker"] = match["ticker"]
            if "kalshi_market_ticker" not in out:
                out["kalshi_market_ticker"] = self.kalshi_markets[0]["ticker"]
            out["kalshi_event_ticker"] = self.kalshi_event_ticker

        if self.poly_valid and self.poly_market:
            out["poly_slug"] = self.poly_slug
            m = None
            if isinstance(self.poly_market, dict):
                if "conditionId" in self.poly_market:
                    m = self.poly_market
                elif "markets" in self.poly_market and self.poly_market["markets"]:
                    # Event: prefer moneyline market
                    mkts = self.poly_market["markets"]
                    m = next((x for x in mkts if x.get("sportsMarketType") == "moneyline"), mkts[0] if mkts else None)
            if m:
                out["poly_condition_id"] = m.get("conditionId")

        # Bolt team matching: validate against Bolt API when key available
        derived_home, derived_away, home_aliases, away_aliases = _extract_bolt_teams(
            self.kalshi_markets, self.poly_market
        )
        bolt_home, bolt_away = derived_home, derived_away

        if bolt_key and derived_home and derived_away:
            game_date = _parse_date_from_slug(self.poly_slug or "") or _parse_date_from_kalshi_ticker(
                self.kalshi_event_ticker or ""
            )
            if game_date:
                api_home, api_away, _ = fetch_bolt_teams(
                    bolt_key, game_date, derived_home, derived_away
                )
                if api_home and api_away:
                    bolt_home, bolt_away = api_home, api_away
                    # Add API names to aliases for robust matching
                    if bolt_home not in home_aliases:
                        home_aliases.insert(0, bolt_home)
                    if bolt_away not in away_aliases:
                        away_aliases.insert(0, bolt_away)

        if bolt_home and bolt_away:
            out["bolt_home"] = bolt_home
            out["bolt_away"] = bolt_away
            out["bolt_home_aliases"] = home_aliases
            out["bolt_away_aliases"] = away_aliases

        return out


def validate_pair(
    kalshi_url: Optional[str] = None,
    poly_url: Optional[str] = None,
    kalshi_ticker: Optional[str] = None,
    poly_slug: Optional[str] = None,
) -> UrlValidationResult:
    """
    Parse URLs (or use raw ticker/slug) and validate both markets.

    Args:
      kalshi_url: Full Kalshi market URL
      poly_url: Full Polymarket URL
      kalshi_ticker: Override - use this ticker directly (skip URL parse)
      poly_slug: Override - use this slug directly (skip URL parse)

    Returns:
      UrlValidationResult with tickers, validation status, and config snippet.
    """
    result = UrlValidationResult()

    # Kalshi
    ticker = kalshi_ticker or (parse_kalshi_url(kalshi_url) if kalshi_url else None)
    if ticker:
        result.kalshi_event_ticker = ticker
        valid, markets, err = validate_kalshi_ticker(ticker)
        result.kalshi_valid = valid
        result.kalshi_markets = markets
        result.kalshi_error = err
    else:
        result.kalshi_error = "No Kalshi URL or ticker provided"

    # Polymarket
    slug = poly_slug or (parse_polymarket_url(poly_url) if poly_url else None)
    if slug:
        result.poly_slug = slug
        valid, data, err = validate_polymarket_slug(slug)
        result.poly_valid = valid
        result.poly_market = data
        result.poly_error = err
    else:
        result.poly_error = "No Polymarket URL or slug provided"

    return result


# --- CLI ---

def main():
    import argparse
    p = argparse.ArgumentParser(description="Extract and validate Kalshi/Polymarket tickers from URLs")
    p.add_argument("--kalshi", "-k", help="Kalshi market URL")
    p.add_argument("--poly", "-p", help="Polymarket URL")
    p.add_argument("--team", "-t", help="Kalshi team ticker suffix (e.g. NMSU, JVST) for config")
    p.add_argument("--config", "-c", action="store_true", help="Print config snippet")
    args = p.parse_args()

    result = validate_pair(kalshi_url=args.kalshi, poly_url=args.poly)

    print("=== Kalshi ===")
    print(f"  Event ticker: {result.kalshi_event_ticker or 'N/A'}")
    print(f"  Valid: {result.kalshi_valid}")
    if result.kalshi_error:
        print(f"  Error: {result.kalshi_error}")
    if result.kalshi_markets:
        for m in result.kalshi_markets[:5]:
            print(f"  Market: {m.get('ticker')} | {m.get('title', '')[:50]}")

    print("\n=== Polymarket ===")
    print(f"  Slug: {result.poly_slug or 'N/A'}")
    print(f"  Valid: {result.poly_valid}")
    if result.poly_error:
        print(f"  Error: {result.poly_error}")
    if result.poly_market and isinstance(result.poly_market, dict):
        q = result.poly_market.get("question") or result.poly_market.get("title", "")
        print(f"  Market: {q[:60]}")

    if args.config and (result.kalshi_valid or result.poly_valid):
        cfg = result.to_config_snippet(
            team_ticker=args.team,
            bolt_key=os.getenv("BOLT_KEY"),
        )
        print("\n=== Config snippet ===")
        for k, v in cfg.items():
            if isinstance(v, list):
                print(f"  \"{k}\": {v},")
            else:
                print(f"  \"{k}\": \"{v}\",")


if __name__ == "__main__":
    main()
