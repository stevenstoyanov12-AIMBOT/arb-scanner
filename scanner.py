"""
Crypto Prediction & Sports Arb Scanner v2
Platforms: Kalshi, SX Bet, Azuro, Overtime, Thales + The Odds API

Verified API endpoints from official documentation.
"""

import os
import requests
import time
from datetime import datetime
from typing import Dict, List, Optional
import json

# =============================================================================
# CONFIGURATION
# =============================================================================

# Telegram alerts (set as environment variables, see .env.example)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# The Odds API (optional - for sharp bookmakers)
# Get free key at https://the-odds-api.com/
THE_ODDS_API_KEY = os.environ.get("THE_ODDS_API_KEY", "")

# Minimum net profit after fees to alert (percent)
MIN_NET_PROFIT_PERCENT = 0.5

# Platform fees (percent)
PLATFORM_FEES = {
    'kalshi': 0.0,       # No trading fees, but 7% on profits (we ignore for simplicity)
    'sx_bet': 0.25,      # 0.25% taker fee
    'azuro': 3.0,        # ~3% margin built into odds
    'overtime': 2.5,     # ~2.5% margin
    'thales': 2.0,       # ~2% margin
}

# Sharp bookmakers (from The Odds API)
SHARP_BOOKMAKERS = {
    'pinnacle': 2.0,
    'betfair_ex_uk': 2.0,
    'smarkets': 2.0,
    'matchbook': 2.0,
}


# =============================================================================
# TELEGRAM ALERTS
# =============================================================================

def send_telegram(message: str) -> bool:
    """Send Telegram alert"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[ALERT] {message[:200]}...")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


# =============================================================================
# KALSHI API
# Docs: https://docs.kalshi.com/
# No auth required for market data
# NOTE: Blocked in Bulgaria and 45+ other countries including UK, Canada, Australia
# =============================================================================

def fetch_kalshi_markets() -> List[Dict]:
    """
    Fetch markets from Kalshi
    Endpoint: GET https://api.elections.kalshi.com/trade-api/v2/markets
    
    NOTE: Kalshi is geo-blocked in many countries including Bulgaria.
    If you get 0 markets, you may need a VPN to US.
    """
    try:
        url = "https://api.elections.kalshi.com/trade-api/v2/markets"
        params = {
            'status': 'open',
            'limit': 200,
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"HTTP {response.status_code}")
            return []
        
        data = response.json()
        markets = []
        
        raw_markets = data.get('markets', [])
        
        for market in raw_markets:
            try:
                # yes_bid/yes_ask are in cents (1-99)
                # Can be None or 0 if no liquidity
                yes_bid = market.get('yes_bid') or 0
                yes_ask = market.get('yes_ask') or 0
                
                # Also check last_price as fallback
                last_price = market.get('last_price') or 50
                
                # Use last_price if no bid/ask
                if yes_ask == 0:
                    yes_ask = last_price
                if yes_bid == 0:
                    yes_bid = last_price
                
                # Skip markets with no price data at all
                if yes_ask == 0 and yes_bid == 0 and last_price == 0:
                    continue
                
                # Convert cents to probability (0-1)
                yes_prob = yes_ask / 100 if yes_ask > 0 else 0.5
                no_prob = (100 - yes_bid) / 100 if yes_bid < 100 else 0.5
                
                # Ensure valid probabilities
                yes_prob = max(0.01, min(0.99, yes_prob))
                no_prob = max(0.01, min(0.99, no_prob))
                
                # Convert to decimal odds
                yes_odds = 1 / yes_prob
                no_odds = 1 / no_prob
                
                markets.append({
                    'platform': 'kalshi',
                    'event_id': market.get('ticker', ''),
                    'event_name': market.get('title', ''),
                    'category': market.get('category', ''),
                    'outcomes': [
                        {'name': 'Yes', 'odds': yes_odds, 'price_cents': yes_ask},
                        {'name': 'No', 'odds': no_odds, 'price_cents': 100 - yes_bid},
                    ],
                })
            except Exception:
                continue
        
        return markets
    
    except Exception as e:
        print(f"error: {e}")
        return []


# =============================================================================
# SX BET API
# Docs: https://api.docs.sx.bet/
# No auth required for market data
# =============================================================================

def fetch_sx_bet_markets() -> List[Dict]:
    """
    Fetch markets from SX Bet
    Endpoint: GET https://api.sx.bet/markets/active
    Note: Odds require separate /orders query (returns markets only here)
    """
    try:
        url = "https://api.sx.bet/markets/active"
        response = requests.get(url, timeout=30)
        
        if response.status_code != 200:
            print(f"HTTP {response.status_code}")
            return []
        
        data = response.json()
        
        if data.get('status') != 'success':
            print(f"API error: {data.get('status')}")
            return []
        
        markets = []
        markets_data = data.get('data', {})
        
        # Handle both list and dict with 'markets' key
        if isinstance(markets_data, dict):
            markets_list = markets_data.get('markets', [])
        else:
            markets_list = markets_data
        
        for market in markets_list:
            try:
                team1 = market.get('teamOneName', '')
                team2 = market.get('teamTwoName', '')
                outcome1 = market.get('outcomeOneName', team1)
                outcome2 = market.get('outcomeTwoName', team2)
                
                if not team1 or not team2:
                    continue
                
                # SX Bet needs orders endpoint for real odds
                # For now, mark as needing odds fetch
                markets.append({
                    'platform': 'sx_bet',
                    'event_id': market.get('marketHash', ''),
                    'event_name': f"{team1} vs {team2}",
                    'sport': market.get('sportLabel', ''),
                    'league': market.get('leagueLabel', ''),
                    'outcomes': [
                        {'name': outcome1, 'odds': None, 'needs_fetch': True},
                        {'name': outcome2, 'odds': None, 'needs_fetch': True},
                    ],
                    'market_hash': market.get('marketHash', ''),
                })
            except Exception:
                continue
        
        return markets
    
    except Exception as e:
        print(f"error: {e}")
        return []


def fetch_sx_bet_odds(market_hash: str) -> Optional[Dict]:
    """
    Fetch odds for a specific SX Bet market
    Endpoint: POST https://api.sx.bet/orders
    """
    try:
        url = "https://api.sx.bet/orders"
        params = {'marketHashes': market_hash}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        if data.get('status') != 'success':
            return None
        
        orders = data.get('data', [])
        
        # Find best odds for each side
        best_odds = {'outcome1': None, 'outcome2': None}
        
        for order in orders:
            implied_odds = order.get('percentageOdds', '')
            if implied_odds:
                # Convert API percentage to decimal odds
                pct = float(implied_odds) / 10**20  # API uses big numbers
                decimal_odds = 1 / pct if pct > 0 else None
                
                if order.get('isMakerBettingOutcomeOne'):
                    if not best_odds['outcome2'] or decimal_odds > best_odds['outcome2']:
                        best_odds['outcome2'] = decimal_odds
                else:
                    if not best_odds['outcome1'] or decimal_odds > best_odds['outcome1']:
                        best_odds['outcome1'] = decimal_odds
        
        return best_odds
    
    except Exception:
        return None


# =============================================================================
# AZURO API (GraphQL) 
# Docs: https://gem.azuro.org/hub/apps/APIs/overview
# NOTE: Feed data now on onchainfeed.org endpoints (Feb 2025)
# =============================================================================

# Production data-feed endpoints (current as of 2025)
AZURO_DATA_FEED_ENDPOINTS = {
    'polygon': 'https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-polygon',
    'gnosis': 'https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-gnosis',
    'base': 'https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-base',
    'chiliz': 'https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-chiliz',
}

# Fallback client API endpoints (for bet history, not odds)
AZURO_CLIENT_ENDPOINTS = {
    'polygon': 'https://thegraph.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-api-polygon-v3',
    'gnosis': 'https://thegraph.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-api-gnosis-v3',
    'base': 'https://thegraph.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-api-base-v3',
}

def fetch_azuro_markets() -> List[Dict]:
    """
    Fetch markets from Azuro GraphQL API
    Uses the new onchainfeed.org data-feed endpoints
    """
    import time
    current_time = int(time.time())
    
    # Query for data-feed subgraph - updated schema
    data_feed_query = """
    query GetGames($currentTime: BigInt!) {
        games(
            first: 100
            where: { 
                startsAt_gt: $currentTime
                hasActiveConditions: true
            }
            orderBy: startsAt
            orderDirection: asc
        ) {
            gameId
            title
            startsAt
            sport { name slug }
            league { name slug }
            participants { name sortOrder }
            conditions(where: { isCreated: true }) {
                conditionId
                outcomes {
                    outcomeId
                    currentOdds
                }
            }
        }
    }
    """
    
    # Simpler fallback query without variables
    simple_query = """
    {
        games(
            first: 100
            orderBy: startsAt
            orderDirection: desc
        ) {
            gameId
            title
            startsAt
            sport { name slug }
            league { name slug }
            participants { name sortOrder }
            conditions {
                conditionId
                outcomes {
                    outcomeId
                    currentOdds
                }
            }
        }
    }
    """
    
    all_markets = []
    
    for chain, endpoint in AZURO_DATA_FEED_ENDPOINTS.items():
        try:
            # Try with variables first
            response = requests.post(
                endpoint,
                json={
                    'query': data_feed_query,
                    'variables': {'currentTime': str(current_time)}
                },
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code != 200:
                # Try simple query as fallback
                response = requests.post(
                    endpoint,
                    json={'query': simple_query},
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            
            if 'errors' in data:
                # Try simple query on error
                response = requests.post(
                    endpoint,
                    json={'query': simple_query},
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )
                if response.status_code == 200:
                    data = response.json()
            
            games = data.get('data', {}).get('games', [])
            
            for game in games:
                try:
                    title = game.get('title', '')
                    participants = game.get('participants', [])
                    
                    # Build title from participants if not present
                    if not title and participants:
                        sorted_parts = sorted(participants, key=lambda x: x.get('sortOrder', 0))
                        names = [p.get('name', '') for p in sorted_parts]
                        title = ' vs '.join(names)
                    
                    if not title:
                        continue
                    
                    # Skip past games
                    starts_at = int(game.get('startsAt', 0))
                    if starts_at > 0 and starts_at < current_time:
                        continue
                    
                    for condition in game.get('conditions', []):
                        outcomes = condition.get('outcomes', [])
                        
                        if len(outcomes) < 2:
                            continue
                        
                        parsed_outcomes = []
                        for i, outcome in enumerate(outcomes[:3]):
                            odds_str = outcome.get('currentOdds', '0')
                            try:
                                odds = float(odds_str) if odds_str else 0
                            except:
                                odds = 0
                            
                            if odds <= 1:
                                continue
                            
                            # Try to get name from participants
                            if participants and i < len(participants):
                                sorted_parts = sorted(participants, key=lambda x: x.get('sortOrder', 0))
                                if i < len(sorted_parts):
                                    name = sorted_parts[i].get('name', '')
                            else:
                                name = ''
                            
                            if not name:
                                name = ['Home', 'Away', 'Draw'][i] if i < 3 else f'Outcome {i+1}'
                            
                            parsed_outcomes.append({
                                'name': name,
                                'odds': odds,
                                'implied_prob': 1/odds,
                            })
                        
                        if len(parsed_outcomes) >= 2:
                            all_markets.append({
                                'platform': 'azuro',
                                'chain': chain,
                                'event_id': game.get('gameId', ''),
                                'event_name': title,
                                'sport': game.get('sport', {}).get('name', ''),
                                'league': game.get('league', {}).get('name', ''),
                                'outcomes': parsed_outcomes,
                            })
                
                except Exception:
                    continue
        
        except Exception:
            continue
    
    return all_markets


# =============================================================================
# OVERTIME API
# Docs: https://docs.overtime.io/
# Note: Protected API requires API key for full access
# =============================================================================

OVERTIME_NETWORKS = {
    'optimism': 10,
    'arbitrum': 42161,
    'base': 8453,
}

def fetch_overtime_markets() -> List[Dict]:
    """
    Fetch markets from Overtime API
    Base URL: https://api.overtime.io
    """
    all_markets = []
    
    for network, chain_id in OVERTIME_NETWORKS.items():
        try:
            # Try the public markets endpoint
            url = f"https://api.overtime.io/v2/{network}/markets"
            response = requests.get(url, timeout=15)
            
            if response.status_code != 200:
                # Try alternative endpoint format
                url = f"https://api.overtime.io/overtime-v2/networks/{chain_id}/markets"
                response = requests.get(url, timeout=15)
            
            if response.status_code != 200:
                continue
            
            data = response.json()
            
            # Handle different response formats
            if isinstance(data, dict):
                if 'markets' in data:
                    markets_list = data['markets']
                elif 'data' in data:
                    markets_list = data['data']
                else:
                    markets_list = list(data.values()) if data else []
            else:
                markets_list = data if isinstance(data, list) else []
            
            for market in markets_list:
                try:
                    if not isinstance(market, dict):
                        continue
                    
                    home = market.get('homeTeam', '')
                    away = market.get('awayTeam', '')
                    
                    if not home or not away:
                        continue
                    
                    # Get odds array
                    odds_data = market.get('odds', [])
                    
                    if not odds_data or len(odds_data) < 2:
                        continue
                    
                    outcomes = []
                    for i, odd in enumerate(odds_data[:3]):
                        if not odd:
                            continue
                        
                        # Odds can be dict or float
                        if isinstance(odd, dict):
                            decimal_odds = odd.get('decimal', 0)
                        else:
                            decimal_odds = float(odd)
                        
                        if decimal_odds <= 1:
                            continue
                        
                        name = home if i == 0 else (away if i == 1 else 'Draw')
                        outcomes.append({
                            'name': name,
                            'odds': decimal_odds,
                            'implied_prob': 1/decimal_odds,
                        })
                    
                    if len(outcomes) >= 2:
                        all_markets.append({
                            'platform': 'overtime',
                            'network': network,
                            'event_id': market.get('gameId', ''),
                            'event_name': f"{home} vs {away}",
                            'sport': market.get('sport', ''),
                            'league': market.get('leagueName', ''),
                            'outcomes': outcomes,
                        })
                
                except Exception:
                    continue
        
        except Exception as e:
            continue
    
    return all_markets


# =============================================================================
# THALES API
# Note: Thales sports is now Overtime. Thales itself is for crypto derivatives.
# We'll skip Thales as Overtime covers sports.
# =============================================================================

def fetch_thales_markets() -> List[Dict]:
    """
    Thales sports betting is now Overtime Markets.
    Thales.io itself is for crypto price predictions (UP/DOWN).
    Skip for sports arb scanning.
    """
    return []


# =============================================================================
# THE ODDS API (Sharp Bookmakers)
# Docs: https://the-odds-api.com/liveapi/guides/v4/
# =============================================================================

def fetch_theoddsapi_markets() -> List[Dict]:
    """
    Fetch odds from The Odds API - sharp bookmakers only
    """
    if not THE_ODDS_API_KEY:
        print("No API key")
        return []
    
    try:
        url = "https://api.the-odds-api.com/v4/sports/upcoming/odds"
        params = {
            'apiKey': THE_ODDS_API_KEY,
            'regions': 'uk,eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal',
            'bookmakers': ','.join(SHARP_BOOKMAKERS.keys()),
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"HTTP {response.status_code}")
            return []
        
        # Show quota remaining
        remaining = response.headers.get('x-requests-remaining', '?')
        print(f"(quota: {remaining})", end=" ")
        
        data = response.json()
        markets = []
        
        for event in data:
            home = event.get('home_team', '')
            away = event.get('away_team', '')
            event_name = f"{home} vs {away}"
            
            for bookmaker in event.get('bookmakers', []):
                bookie_key = bookmaker.get('key', '')
                
                if bookie_key not in SHARP_BOOKMAKERS:
                    continue
                
                fee = SHARP_BOOKMAKERS[bookie_key]
                
                for market in bookmaker.get('markets', []):
                    if market.get('key') != 'h2h':
                        continue
                    
                    outcomes = []
                    for outcome in market.get('outcomes', []):
                        odds = outcome.get('price', 0)
                        if odds > 1:
                            outcomes.append({
                                'name': outcome.get('name', ''),
                                'odds': odds,
                                'implied_prob': 1/odds,
                            })
                    
                    if len(outcomes) >= 2:
                        markets.append({
                            'platform': f'theoddsapi_{bookie_key}',
                            'platform_display': bookie_key.replace('_', ' ').title(),
                            'fee_percent': fee,
                            'event_id': event.get('id', ''),
                            'event_name': event_name,
                            'sport': event.get('sport_key', ''),
                            'outcomes': outcomes,
                        })
        
        return markets
    
    except Exception as e:
        print(f"error: {e}")
        return []


# =============================================================================
# ARB CALCULATION
# =============================================================================

def calculate_arb(odds1: float, odds2: float, fee1: float, fee2: float) -> Dict:
    """Calculate arbitrage opportunity between two outcomes"""
    if not odds1 or not odds2 or odds1 <= 1 or odds2 <= 1:
        return {'is_arb': False}
    
    prob1 = 1 / odds1
    prob2 = 1 / odds2
    total_prob = prob1 + prob2
    
    # Gross arb percentage (negative means no arb)
    gross_arb = (1 - total_prob) * 100
    
    # Net after fees
    total_fees = fee1 + fee2
    net_arb = gross_arb - total_fees
    
    # Optimal stake distribution for $100 total
    stake1 = 100 * prob1 / total_prob
    stake2 = 100 * prob2 / total_prob
    
    # Expected profit
    payout1 = stake1 * odds1
    payout2 = stake2 * odds2
    guaranteed = min(payout1, payout2)
    net_profit = guaranteed - 100 - (total_fees)
    
    return {
        'is_arb': net_arb > 0,
        'gross_arb_percent': gross_arb,
        'net_arb_percent': net_arb,
        'total_fees_percent': total_fees,
        'stake1': stake1,
        'stake2': stake2,
        'net_profit': net_profit,
    }


def events_match(name1: str, name2: str) -> bool:
    """Check if two event names likely refer to the same event - STRICT matching"""
    # Normalize names
    stopwords = {'vs', 'v', '-', 'at', 'the', '@', 'fc', 'sc', 'cf', 'yes', 'no'}
    
    # Clean and split
    clean1 = name1.lower().replace(',', ' ').replace('-', ' ')
    clean2 = name2.lower().replace(',', ' ').replace('-', ' ')
    
    words1 = set(clean1.split()) - stopwords
    words2 = set(clean2.split()) - stopwords
    
    if not words1 or not words2:
        return False
    
    # Skip if either name looks like a parlay/multi (has multiple team names)
    if len(words1) > 6 or len(words2) > 6:
        return False
    
    # Require at least 2 words to match (both team names should match)
    overlap = words1 & words2
    if len(overlap) < 2:
        return False
    
    # Require high overlap ratio (at least 70%)
    min_words = min(len(words1), len(words2))
    if len(overlap) / min_words < 0.7:
        return False
    
    return True


def find_arbs(all_markets: List[Dict]) -> List[Dict]:
    """Find arbitrage opportunities across all markets"""
    arbs = []
    
    # 2-way sports only (no draws possible)
    TWO_WAY_SPORTS = {
        'basketball', 'nba', 'ncaa', 'euroleague', 'wnba',
        'tennis', 'atp', 'wta', 'itf',
        'mma', 'ufc', 'bellator', 'pfl', 'boxing',
        'esports', 'csgo', 'dota', 'league of legends', 'valorant',
        'baseball', 'mlb',
        'american football', 'nfl', 'ncaaf',
    }
    
    # Compare each pair of markets
    for i, m1 in enumerate(all_markets):
        for m2 in all_markets[i+1:]:
            # Skip same platform
            if m1['platform'] == m2['platform']:
                continue
            
            # Check if events match
            if not events_match(m1['event_name'], m2['event_name']):
                continue
            
            # Skip if either market has 3+ outcomes (indicates 3-way market like soccer)
            if len(m1.get('outcomes', [])) > 2 or len(m2.get('outcomes', [])) > 2:
                continue
            
            # Check sport type - only allow 2-way sports
            sport1 = m1.get('sport', '').lower()
            sport2 = m2.get('sport', '').lower()
            
            is_two_way = False
            for two_way in TWO_WAY_SPORTS:
                if two_way in sport1 or two_way in sport2:
                    is_two_way = True
                    break
            
            # If sport is unknown, check if market only has 2 outcomes
            if not is_two_way and not sport1 and not sport2:
                if len(m1.get('outcomes', [])) == 2 and len(m2.get('outcomes', [])) == 2:
                    is_two_way = True
            
            if not is_two_way:
                continue
            
            # Get fees
            fee1 = m1.get('fee_percent', PLATFORM_FEES.get(m1['platform'], 3.0))
            fee2 = m2.get('fee_percent', PLATFORM_FEES.get(m2['platform'], 3.0))
            
            # Check all outcome combinations
            for o1 in m1['outcomes']:
                for o2 in m2['outcomes']:
                    # Only compare valid opposite outcomes
                    n1 = o1['name'].lower()
                    n2 = o2['name'].lower()
                    
                    # Skip Draw - not a valid arb leg
                    if n1 == 'draw' or n2 == 'draw':
                        continue
                    
                    # Skip if same outcome
                    if n1 == n2:
                        continue
                    
                    # For Yes/No markets, must be opposite
                    if n1 in ('yes', 'no') and n2 in ('yes', 'no'):
                        if n1 == n2:
                            continue
                    # For team markets (Home/Away), must be opposite
                    elif n1 in ('home', 'away') and n2 in ('home', 'away'):
                        if n1 == n2:
                            continue
                    
                    # Skip if odds not available
                    if not o1.get('odds') or not o2.get('odds'):
                        continue
                    
                    arb = calculate_arb(o1['odds'], o2['odds'], fee1, fee2)
                    
                    if arb['is_arb'] and arb['net_arb_percent'] >= MIN_NET_PROFIT_PERCENT:
                        p1_name = m1.get('platform_display', m1['platform'])
                        p2_name = m2.get('platform_display', m2['platform'])
                        
                        arbs.append({
                            'event': m1['event_name'],
                            'platform1': {
                                'name': p1_name,
                                'outcome': o1['name'],
                                'odds': o1['odds'],
                                'fee': fee1,
                            },
                            'platform2': {
                                'name': p2_name,
                                'outcome': o2['name'],
                                'odds': o2['odds'],
                                'fee': fee2,
                            },
                            **arb
                        })
    
    # Sort by net profit descending
    return sorted(arbs, key=lambda x: x['net_arb_percent'], reverse=True)


# =============================================================================
# SCANNER
# =============================================================================

def scan_all_platforms() -> List[Dict]:
    """Scan all platforms and find arbs"""
    print(f"\n{'='*50}")
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC] Scanning...")
    print('='*50)
    
    all_markets = []
    
    # Kalshi
    print("  Kalshi...", end=" ", flush=True)
    markets = fetch_kalshi_markets()
    print(f"{len(markets)} markets")
    all_markets.extend(markets)
    
    # SX Bet
    print("  SX Bet...", end=" ", flush=True)
    markets = fetch_sx_bet_markets()
    print(f"{len(markets)} markets")
    all_markets.extend(markets)
    
    # Azuro
    print("  Azuro...", end=" ", flush=True)
    markets = fetch_azuro_markets()
    print(f"{len(markets)} markets")
    all_markets.extend(markets)
    
    # Overtime
    print("  Overtime...", end=" ", flush=True)
    markets = fetch_overtime_markets()
    print(f"{len(markets)} markets")
    all_markets.extend(markets)
    
    # The Odds API (sharp bookies)
    print("  The Odds API...", end=" ", flush=True)
    markets = fetch_theoddsapi_markets()
    print(f"{len(markets)} markets")
    all_markets.extend(markets)
    
    print(f"\n  Total: {len(all_markets)} markets")
    
    # Find arbs
    arbs = find_arbs(all_markets)
    
    return arbs


def format_arb_alert(arb: Dict) -> str:
    """Format arb as Telegram message"""
    return f"""🔔 <b>ARB FOUND</b>

<b>Event:</b> {arb['event'][:50]}

<b>{arb['platform1']['name']}:</b>
  {arb['platform1']['outcome']} @ {arb['platform1']['odds']:.2f}
  Fee: {arb['platform1']['fee']}%

<b>{arb['platform2']['name']}:</b>
  {arb['platform2']['outcome']} @ {arb['platform2']['odds']:.2f}
  Fee: {arb['platform2']['fee']}%

Gross: {arb['gross_arb_percent']:.2f}%
Fees: -{arb['total_fees_percent']:.2f}%
<b>Net: +{arb['net_arb_percent']:.2f}%</b>

Stakes ($100):
  ${arb['stake1']:.2f} on {arb['platform1']['name']}
  ${arb['stake2']:.2f} on {arb['platform2']['name']}

Expected profit: ${arb['net_profit']:.2f}"""


def run_scanner(interval: int = 60):
    """Run continuous scanner"""
    print("\n" + "="*50)
    print("ARB SCANNER v2")
    print(f"Platforms: Kalshi, SX Bet, Azuro, Overtime" + (", Sharp Bookies" if THE_ODDS_API_KEY else ""))
    print(f"Min profit: {MIN_NET_PROFIT_PERCENT}%")
    print(f"Interval: {interval}s")
    print("="*50)
    
    send_telegram("🔍 Arb Scanner Started")
    
    seen_arbs = set()
    
    while True:
        try:
            arbs = scan_all_platforms()
            
            if arbs:
                print(f"\n✅ Found {len(arbs)} arbs!")
                for arb in arbs:
                    # Create unique key for deduplication
                    key = f"{arb['event']}_{arb['platform1']['name']}_{arb['platform2']['name']}"
                    
                    if key not in seen_arbs:
                        seen_arbs.add(key)
                        alert = format_arb_alert(arb)
                        print(alert)
                        print("-" * 40)
                        send_telegram(alert)
            else:
                print("\n  No arbs found above threshold")
            
            # Clear old seen arbs periodically
            if len(seen_arbs) > 100:
                seen_arbs = set(list(seen_arbs)[-50:])
        
        except Exception as e:
            print(f"\nError during scan: {e}")
        
        print(f"\nNext scan in {interval}s...")
        time.sleep(interval)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Crypto Arb Scanner v2')
    parser.add_argument('--test', action='store_true', help='Test API connections')
    parser.add_argument('--scan', action='store_true', help='Single scan')
    parser.add_argument('--loop', action='store_true', help='Continuous scanning')
    parser.add_argument('--interval', type=int, default=60, help='Scan interval in seconds')
    parser.add_argument('--min-profit', type=float, default=0.5, help='Minimum net profit %')
    
    args = parser.parse_args()
    
    if args.min_profit:
        MIN_NET_PROFIT_PERCENT = args.min_profit
    
    if args.test:
        print("Testing API connections...\n")
        
        print("1. Kalshi")
        print("   URL: https://api.elections.kalshi.com/trade-api/v2/markets")
        m = fetch_kalshi_markets()
        print(f"   Result: {len(m)} markets")
        if m:
            print(f"   Sample: {m[0]['event_name'][:60]}")
        print()
        
        print("2. SX Bet")
        print("   URL: https://api.sx.bet/markets/active")
        m = fetch_sx_bet_markets()
        print(f"   Result: {len(m)} markets")
        if m:
            print(f"   Sample: {m[0]['event_name'][:60]}")
        print()
        
        print("3. Azuro (GraphQL)")
        print("   URL: https://thegraph.azuro.org/subgraphs/name/azuro-protocol/...")
        m = fetch_azuro_markets()
        print(f"   Result: {len(m)} markets")
        if m:
            print(f"   Sample: {m[0]['event_name'][:60]}")
        print()
        
        print("4. Overtime")
        print("   URL: https://api.overtime.io/v2/{network}/markets")
        m = fetch_overtime_markets()
        print(f"   Result: {len(m)} markets")
        if m:
            print(f"   Sample: {m[0]['event_name'][:60]}")
        print()
        
        print("5. The Odds API")
        print("   URL: https://api.the-odds-api.com/v4/sports/upcoming/odds")
        m = fetch_theoddsapi_markets()
        print(f"   Result: {len(m)} markets")
        if m:
            print(f"   Sample: {m[0]['event_name'][:60]}")
        print()
        
        print("="*50)
        print("Test complete!")
    
    elif args.scan:
        arbs = scan_all_platforms()
        if arbs:
            print(f"\n{'='*50}")
            print(f"Found {len(arbs)} arbitrage opportunities:")
            print("="*50)
            for arb in arbs:
                print(format_arb_alert(arb))
                print("-" * 40)
        else:
            print("\n❌ No arbitrage opportunities found")
    
    elif args.loop:
        run_scanner(args.interval)
    
    else:
        parser.print_help()
