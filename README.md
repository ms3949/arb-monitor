# ⚡ Cross-Exchange Arb Monitor

Real-time arbitrage dashboard between **Kalshi** and **Polymarket** for NCAAB basketball markets.

![Dashboard](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)

## What It Does

1. **Browse** — Auto-discovers active NCAAB games on both Kalshi (65+ markets) and Polymarket, with fuzzy team-name matching
2. **Match** — Select a game from each exchange, validate they're the same event (team + date matching)
3. **Monitor** — Connects to both WebSocket feeds for live bid/ask data, plots spread in real-time, and flags arbitrage opportunities (|spread| > 3%)
4. **Analyze** — Post-session statistical analysis: spread distribution, arb windows, summary stats

## Quick Start

### 1. Clone & Setup

```bash
cd streamlit_app
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` with your **Kalshi** credentials:

```
KALSHI_KEY_ID=your_api_key_id
KALSHI_PRIVATE_KEY_PATH=/path/to/your/kalshi_private_key.pem
```

> **How to get Kalshi API keys:** Sign up at [kalshi.com](https://kalshi.com), go to Settings → API Keys → Generate. Download the private key `.pem` file and note your Key ID.

> **Polymarket** does not require API keys for read-only market data.

### 3. Run

```bash
streamlit run dashboard.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## How to Use

### Phase 1: Browse & Match
- Markets auto-load on first visit (~15s for Poly discovery)
- Select a **Kalshi game** and a **Polymarket game** from the sidebar dropdowns
- Click **🔍 Check Match** — the app validates teams + date
- If matched (HIGH or MEDIUM confidence), click **🚀 Run Bot**

### Phase 2: Live Monitoring
- Live spread chart updates every second
- Metric cards show Kalshi mid, Poly mid, spread, and arb event count
- Pulsing **🚨 ARB OPPORTUNITY** alert when |spread| > 3%
- Orderbook tables show bid/ask/size for both exchanges

### Phase 3: Post-Session Analysis
- Click **🛑 Stop & Analyze** to end monitoring
- Spread time-series with arb event markers
- Spread distribution histogram
- Summary statistics table (mean/std/max/min spread, session duration, etc.)

## Project Structure

```
streamlit_app/
├── dashboard.py          # Main Streamlit UI (all 3 phases)
├── fetch_markets.py      # Kalshi + Poly API fetchers, match validation
├── .env.example          # Template for API keys
├── .gitignore
├── config/               # Settings & game configuration
├── discovery/            # Market discovery tools
├── execution/            # Trading engine, REST client, signals
├── feeds/                # WebSocket feed handlers
├── analysis/             # Logging & lead-lag analysis
└── strategies/           # Arb strategy definitions
```

## Key Design Decisions

| Decision | Why |
|----------|-----|
| **Slug construction** for Poly discovery | Gamma API `slug_contains` doesn't work for sports markets, so we build slugs from Kalshi team names |
| **ThreadPoolExecutor** (10 workers) | Parallel slug lookups cut Poly discovery from 5min → 15s |
| **Single CLOB token subscription** | Subscribing to both outcome tokens and flipping prices was unreliable |
| **Settled market filter** (>95% outcome) | Prevents matching against games already decided |
| **Home team ticker matching** | Kalshi has separate tickers per team (e.g., `-UNLV`, `-USU`); we pick the one matching the home team |

## Dependencies

```
streamlit
plotly
pandas
numpy
websockets
cryptography
python-dotenv
requests
```

Install all at once:

```bash
pip install streamlit plotly pandas numpy websockets cryptography python-dotenv requests
```

## Notes

- **Polymarket CBB markets are often illiquid** — expect wide bid/ask spreads (0.30–0.70+ range)
- **Kalshi requires authentication** for WebSocket orderbook data
- The monitor phase uses `threading` + `queue` to run WS feeds in the background while Streamlit re-renders
- All times are local to your machine

## License

For personal/educational use only. Not financial advice. Use at your own risk.
