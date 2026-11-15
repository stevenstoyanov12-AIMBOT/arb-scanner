# Crypto Arb Scanner v2

Scans prediction markets and sports betting platforms for arbitrage opportunities.

## Demo

`demo/index.html` is a small browser demo of the logic. It simulates a two-outcome fight with odds on five platforms and shows the scanner's steps live: best prices, implied total, gross and net edge, stake split and whether an alert would fire. The odds in the demo are simulated.

## Platforms

| Platform | Type | Fee | API Status | Notes |
|----------|------|-----|------------|-------|
| **Kalshi** | Prediction markets | ~0% | ✅ Public | US regulated exchange |
| **SX Bet** | Sports betting | 0.25% | ✅ Public | Peer-to-peer exchange |
| **Azuro** | Sports betting | ~3% | ✅ GraphQL | Multi-chain (Polygon, Gnosis, Arbitrum) |
| **Overtime** | Sports betting | ~2.5% | ⚠️ Protected | Full access needs API key |
| **The Odds API** | Odds aggregator | varies | ✅ 500 free/mo | Sharp bookmakers data |

## API Endpoints (Verified)

### Kalshi
```
GET https://api.elections.kalshi.com/trade-api/v2/markets?status=open
```
- No auth required for market data
- Returns yes_bid, yes_ask in cents (1-99)
- Docs: https://docs.kalshi.com/

### SX Bet
```
GET https://api.sx.bet/markets/active
```
- No auth required
- Returns markets but need /orders endpoint for best odds
- Docs: https://api.docs.sx.bet/

### Azuro
```
POST https://thegraph.azuro.org/subgraphs/name/azuro-protocol/azuro-api-polygon-v3
```
GraphQL query for games and odds.
- Chains: Polygon, Gnosis, Arbitrum, Linea, Chiliz
- Docs: https://gem.azuro.org/subgraph/overview

### Overtime
```
GET https://api.overtime.io/v2/{network}/markets
```
- Networks: optimism, arbitrum, base
- Protected API requires API key for full access
- Public endpoint may have limited data
- Docs: https://docs.overtime.io/

### The Odds API
```
GET https://api.the-odds-api.com/v4/sports/upcoming/odds
```
- 500 requests/month free tier
- Get key: https://the-odds-api.com/
- Docs: https://the-odds-api.com/liveapi/guides/v4/

## Setup

1. Set your credentials as environment variables (see `.env.example`):
```bash
export TELEGRAM_BOT_TOKEN=your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export THE_ODDS_API_KEY=your_key  # optional
```
Without Telegram credentials, alerts print to the console.

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

```bash
# Test API connections
python scanner.py --test

# Single scan
python scanner.py --scan

# Continuous scanning (every 60s)
python scanner.py --loop

# Custom interval and min profit
python scanner.py --loop --interval 30 --min-profit 2.0
```

## How It Works

1. Fetches odds from all platforms
2. Matches events across platforms (fuzzy name matching)
3. For each matching event, checks opposite outcomes
4. Calculates: `gross_arb = (1 - 1/odds1 - 1/odds2) * 100`
5. Subtracts platform fees: `net_arb = gross_arb - fee1 - fee2`
6. Alerts via Telegram if net_arb > threshold

## Best Arb Combinations

| Platforms | Combined Fees | Best For |
|-----------|---------------|----------|
| Kalshi + SX Bet | 0.25% | Lowest fees |
| Kalshi + Overtime | 2.5% | Prediction vs sports |
| SX Bet + Azuro | 3.25% | Sports cross-platform |
| Azuro + Overtime | 5.5% | Less likely to find arbs |

## Notes

- **Polymarket**: Banned in Bulgaria, removed from scanner
- **Thales**: Now integrated into Overtime, skipped
- **Odds change fast**: Manual betting has latency risk
- **Liquidity**: Scanner doesn't check volume/liquidity

## Troubleshooting

If APIs fail:
1. Check if your IP is blocked (use VPN)
2. APIs change frequently - may need endpoint updates
3. Some platforms geo-restrict certain countries
