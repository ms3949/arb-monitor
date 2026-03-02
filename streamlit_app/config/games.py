"""
Game configuration — auto-populated by discovery at startup.
"""
import json
import requests

from .settings import BOLT_KEY

# --- Game Configuration (populated at startup by discover_games) ---
CONFIG = {}

# --- Resolved IDs (populated at runtime) ---
RESOLVED_IDS = {
    "poly_asset_ids": {}   # condition_id -> [asset_id, ...]
}


def resolve_poly_ids():
    """Resolve poly_condition_id to CLOB asset_id via Gamma API."""
    print("Resolving Polymarket asset IDs...")
    for game, cfg in CONFIG.items():
        cond_id = (cfg.get("poly_condition_id") or "").strip()
        if not cond_id:
            continue
        cond_id_norm = cond_id.lower()
        if not cond_id_norm.startswith("0x"):
            cond_id_norm = "0x" + cond_id_norm

        try:
            # 1. Try Slug First
            slug = cfg.get("poly_slug")
            if slug:
                try:
                    r = requests.get(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=10)
                    if r.status_code == 200:
                        data_s = r.json()
                        ms = data_s if isinstance(data_s, list) else [data_s]
                        if ms:
                            m = ms[0]
                            raw = m.get("clobTokenIds")
                            if raw is not None:
                                clob_ids = json.loads(raw) if isinstance(raw, str) else raw
                                if clob_ids:
                                    asset_ids = [str(aid) for aid in clob_ids]
                                    RESOLVED_IDS["poly_asset_ids"][cond_id] = asset_ids
                                    print(f"  {game}: Resolved via slug -> Asset {asset_ids[0][:12]}...")
                                    continue
                except Exception as e:
                    print(f"  {game}: Slug resolve error: {e}")

            # 2. Fallback: condition_id
            for param in ("condition_id", "conditionId"):
                url = f"https://gamma-api.polymarket.com/markets?{param}={cond_id}"
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if not data:
                    continue
                markets = data if isinstance(data, list) else [data]
                market = markets[0] if markets else None
                if not market:
                    continue
                raw = market.get("clobTokenIds")
                if raw is None:
                    continue
                clob_ids = json.loads(raw) if isinstance(raw, str) else raw
                if not clob_ids:
                    continue
                asset_ids = [str(aid) for aid in clob_ids]
                RESOLVED_IDS["poly_asset_ids"][cond_id] = asset_ids
                print(f"  {game}: Resolved {cond_id[:10]}... -> {len(asset_ids)} asset(s)")
                break

            if cond_id not in RESOLVED_IDS["poly_asset_ids"]:
                print(f"  {game}: Failed to resolve Poly Asset ID.")

        except Exception as e:
            print(f"  {game}: Error: {e}")
