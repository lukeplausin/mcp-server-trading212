import httpx
import os
from datetime import datetime, timedelta
import json
from typing import Any, Dict, Optional
import redis
import pickle
from fuzzywuzzy import fuzz, process as fuzzy_process
from cachetools import TTLCache


SYMBOLS = {
    "GBP": "£",
    "GBX": "p",
    "USD": "$",
    "EUR": "€",
    "CHF": "₣",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "INR": "₹",
    "MXN": "MX$",
    "BRL": "R$",
    "RUB": "₽",
    "ZAR": "R",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "PLN": "zł",
    "": "U"
}

# Should this inherit the MCP "server" class? Not sure...
class Trading212API:
    """Simple client for the Trading212 API with Redis caching support"""
    
    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 300, environment: str = "demo"):
        """
        Initialize with an API key and cache configuration
        
        Args:
            api_key: Trading212 API key. If None, will try to get from TRADING212_API_KEY env var
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
        """

        if environment not in ["demo", "live"]:
            raise RuntimeError(f"Invalid environment {environment}, must be 'live' or 'demo'.")
        self.base_url = f"https://{environment}.trading212.com/api/v0"
        self.api_key = api_key or os.environ.get("TRADING212_API_KEY")
        if not self.api_key:
            raise RuntimeError("API key is required. Set it directly or via TRADING212_API_KEY environment variable.")

        self.timeout = 30.0
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json"
            },
            timeout=self.timeout
        )

        # Initialize cache
        self.cache_ttl = cache_ttl
        self.redis = None
        self.memcache = None

        try:
            redis_host = os.environ.get("REDIS_HOST", "localhost")
            redis_port = int(os.environ.get("REDIS_PORT", "6379"))
            redis_db = int(os.environ.get("REDIS_DB", "0"))
            
            self.redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=False,
                socket_connect_timeout=5
            )
            self._ensure_redis_connection()
        except Exception as e:
            self.redis = None
            self.memcache = TTLCache(maxsize=100, ttl=self.cache_ttl)

    # Caching
    def _ensure_redis_connection(self) -> None:
        """Ensure Redis connection is working"""
        try:
            self.redis.ping()
        except redis.ConnectionError:
            raise ConnectionError("Could not connect to Redis. Make sure Redis is running and accessible.")

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis cache if it exists"""
        if self.redis:
            cached_data = self.redis.get(key)
            if cached_data:
                return pickle.loads(cached_data)
        if self.memcache and key in self.memcache:
            cached_data = self.memcache[key]
            if cached_data:
                return pickle.loads(cached_data)
        return None

    def _set_in_cache(self, key: str, data: Dict[str, Any]) -> None:
        """Store data in Redis cache with expiration time"""
        if self.redis:
            serialized_data = pickle.dumps(data)
            self.redis.setex(key, self.cache_ttl, serialized_data)
        if isinstance(self.memcache, TTLCache):
            self.memcache[key] = pickle.dumps(data)

    def _clear_cache_key(self, key: str) -> None:
        """Store data in Redis cache with expiration time"""
        if self.redis:
            self.redis.setex(key, 1, None)
        if isinstance(self.memcache, TTLCache):
            self.memcache[key] = None

    def clear_cache(self) -> None:
        """Clear all cached data"""
        # Delete all keys starting with t212:
        for key in self.redis.keys("t212:*"):
            self.redis.delete(key)
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        keys = self.redis.keys("t212:*")
        return {
            "total_keys": len(keys),
            "portfolio_cached": bool(self.redis.exists("t212:portfolio")),
            "account_info_cached": bool(self.redis.exists("t212:account_info")),
            "account_balance_cached": bool(self.redis.exists("t212:account_balance")),
        }

    # Account info
    def get_portfolio(self) -> Dict[str, Any]:
        """Retrieve the current portfolio positions"""
        cache_key = "t212:portfolio"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        response = self.client.get("/equity/portfolio")
        response.raise_for_status()
        data = response.json()
        self._set_in_cache(cache_key, data)
        return data
    
    def get_account_info(self) -> Dict[str, Any]:
        """Retrieve account information"""
        cache_key = "t212:account_info"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        response = self.client.get("/equity/account/info")
        response.raise_for_status()
        data = response.json()
        self._set_in_cache(cache_key, data)
        return data
    
    def get_account_balance(self) -> Dict[str, Any]:
        """Retrieve account balance information"""
        cache_key = "t212:account_balance"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        response = self.client.get("/equity/account/cash")
        response.raise_for_status()
        data = response.json()
        self._set_in_cache(cache_key, data)
        return data

    def get_equity_info(self, ticker: str = None) -> Dict[str, Any]:
        """Get detailed information about a specific equity"""
        # cache_key = f"t212:equity_info:{symbol}"
        cache_key = f"t212:equity_info:all"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            data_by_symbol = cached_data
        else:
            response = self.client.get("/equity/metadata/instruments")
            response.raise_for_status()
            data = response.json()
            data_by_symbol = {item['ticker']: item for item in data}
            self._set_in_cache(cache_key, data_by_symbol)

        if ticker:
            return data_by_symbol[ticker] if ticker in data_by_symbol.keys() else None
        else:
            return data_by_symbol

    def search_instruments(self, search_term: str, threshold: int = 70, limit: int = 15) -> Dict[str, Any]:
        """
        Fuzzy and partial match search of instruments based on a search term
        
        :param search_term: The search string.
        :param threshold: Minimum match score to include in results (0-100).
        :param limit: Max number of results to return.
        :return: List of matching instruments.
        """
        all_equities = self.get_equity_info()
        equity_names = {equity['ticker']: equity['name'] for equity in all_equities.values()}

        results = fuzzy_process.extract(search_term, equity_names, scorer=fuzz.partial_ratio, limit=limit)
        return {
            ticker: all_equities[ticker]
            for (name, score, ticker) in results if score >= threshold
        }


    def list_equities(self) -> list[str]:
        """Get a list of traded tickers"""
        data_by_symbol = self.get_equity_info()
        return list(data_by_symbol.keys())

    def get_pies(self) -> Dict[str, Any]:
        """Retrieve information about pies"""
        cache_key = "t212:pies"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        response = self.client.get("/equity/pies")
        response.raise_for_status()
        data = response.json()
        self._set_in_cache(cache_key, data)
        return data

    def get_pie_details(self, id: int) -> Dict[str, Any]:
        """Retrieve information about pies"""
        cache_key = f"t212:pies:{id}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data
            
        response = self.client.get(f"/equity/pies/{id}")
        response.raise_for_status()
        data = response.json()
        self._set_in_cache(cache_key, data)
        return data

    # Tools:
    def create_market_order(self, ticker: str, quantity: float) -> Dict[str, Any]:
        """Create a working market order"""
        response = self.client.post("/equity/orders/market", json={
            "ticker": ticker,
            "quantity": quantity,
        })
        response.raise_for_status()
        data = response.json()
        return data

    def create_limit_order(self, ticker: str, quantity: float, limitPrice: float, timeValidity: str = "DAY") -> Dict[str, Any]:
        """Create a working limit order"""
        response = self.client.post("/equity/orders/market", json={
            "ticker": ticker,
            "quantity": quantity,
            "limitPrice": limitPrice,
            "timeValidity": timeValidity
        })
        response.raise_for_status()
        data = response.json()
        return data

    def create_stop_order(self, ticker: str, quantity: float, stopPrice: float, timeValidity: str = "DAY") -> Dict[str, Any]:
        """Create a working stop order"""
        response = self.client.post("/equity/orders/market", json={
            "ticker": ticker,
            "quantity": quantity,
            "stopPrice": stopPrice,
            "timeValidity": timeValidity
        })
        response.raise_for_status()
        data = response.json()
        return data

    def create_stop_limit_order(self, ticker: str, quantity: float, stopPrice: float, limitPrice: float, timeValidity: str = "DAY") -> Dict[str, Any]:
        """Create a working stop/limit order"""
        response = self.client.post("/equity/orders/market", json={
            "ticker": ticker,
            "quantity": quantity,
            "stopPrice": stopPrice,
            "limitPrice": limitPrice,
            "timeValidity": timeValidity
        })
        response.raise_for_status()
        data = response.json()
        return data

    def update_pie(
            self, id: int, dividendCashAction: str = None, endDate: str = None,
            goal: int = 0, icon: str = None, instrumentShares: Dict[str, float] = None, name: str = None) -> Dict[str, Any]:
        """Update a Trading212 pie"""

        payload = {}
        if dividendCashAction:
            payload["dividendCashAction"] = dividendCashAction
        if endDate:
            payload["endDate"] = endDate
        if goal:
            payload["goal"] = goal
        if icon:
            payload["icon"] = icon
        if instrumentShares:
            payload["instrumentShares"] = instrumentShares
        if name:
            payload["endDate"] = name

        response = self.client.post(
            f"/equity/pies/{id}",
            json=payload
        )
        response.raise_for_status()

        cache_key = f"t212:pies:{id}"
        self._clear_cache_key(cache_key)

        data = response.json()
        return data

def format_currency(value, currency_code="GBP"):
    """Format a currency value with 2 decimal places"""
    symbol = SYMBOLS[currency_code]
    return f"{symbol}{value:.2f}"

def write_json_file(data, file_path=os.path.expanduser(os.path.join("~", "Downloads", "folio.json"))):
    with open(file_path, 'w') as f:
        f.write(json.dumps(data, indent=2))

def print_separator(length=65):
    """Print a separator line"""
    print("-" * length)

def print_equity_info(equity_info):
    """Print formatted equity information"""
    print("\n=== Equity Information ===")
    print(f"Symbol: {equity_info['ticker']}")
    print(f"Name: {equity_info['name']}")
    print(f"Exchange: {equity_info['exchange']}")
    print(f"Currency: {equity_info['currencyCode']}")
    print(f"Current Price: {format_currency(equity_info['currentPrice'], equity_info['currencyCode'])}")
    print(f"Bid: {format_currency(equity_info['bid'], equity_info['currencyCode'])}")
    print(f"Ask: {format_currency(equity_info['ask'], equity_info['currencyCode'])}")
    print(f"Day Change: {format_currency(equity_info['dayChange'], equity_info['currencyCode'])}")
    print(f"Day Change %: {equity_info['dayChangePercent']:.2f}%")
    print(f"Volume: {equity_info['volume']:,}")
    print(f"Market Cap: {format_currency(equity_info['marketCap'], equity_info['currencyCode'])}")
    print(f"ISIN: {equity_info['isin']}")
    print(f"Trading Hours: {equity_info['tradingHours']}")

def main():
    try:
        print("Connecting to Trading212 API...")
        api = Trading212API()
        
        # Get account information
        account_info = api.get_account_info()
        print("\n=== Account Information ===")
        print(f"Account ID: {account_info['id']}")
        print(f"Currency: {account_info['currencyCode']}")
        
        # Get account balance
        balance_info = api.get_account_balance()
        print("\n=== Account Balance ===")
        print(f"Total Balance: {format_currency(balance_info['total'], account_info['currencyCode'])}")
        print(f"Free Cash: {format_currency(balance_info['free'], account_info['currencyCode'])}")
        print(f"Invested Amount: {format_currency(balance_info['invested'], account_info['currencyCode'])}")
        print(f"P&L: {format_currency(balance_info['ppl'], account_info['currencyCode'])}")
        
        # Get portfolio positions
        portfolio = api.get_portfolio()
        
        if not portfolio:
            print("\nYour portfolio is empty.")
            return
        
        print(f"\n=== Portfolio Positions ({len(portfolio)}) ===")
        print(f"{'Symbol':<10} {'Quantity':<10} {'Current Price':<15} {'Market Value':<15} {'P/L':<15}")
        print_separator()
        
        total_value = 0
        total_pl = 0
        
        for position in portfolio:
            # Get and display detailed information for each position
            symbol = position['ticker']
            try:
                equity_info = api.get_equity_info(symbol)
                # print_equity_info(equity_info)
            except httpx.HTTPError as e:
                print(f"Could not fetch detailed information for {symbol}: {e}")
                equity_info = None

            position['equity_info'] = equity_info
            currency = position['equity_info']['currencyCode'] if position['equity_info'] else ''
            quantity = position['quantity']
            current_price = position['currentPrice']
            market_value = quantity * current_price
            pl = position['ppl']
            # The logic in this is flawed due to invalid currency conversions
            total_value += market_value
            total_pl += pl
            
            print(f"{symbol:<10} {quantity:<10.2f} {format_currency(current_price, currency):<15} {format_currency(market_value, currency):<15} {format_currency(pl, currency):<15}")
            
        print_separator()
        print(f"{'TOTAL':<10} {'':^10} {'':^15} {format_currency(total_value):<15} {format_currency(total_pl):<15}")

        write_json_file(portfolio)
        all_equities = api.get_equity_info()
        write_json_file(all_equities, os.path.expanduser(os.path.join("~", "Downloads", "equity_info.json")))
        equity_names = {equity['ticker']: equity['name'] for equity in all_equities.values()}
        write_json_file(equity_names, os.path.expanduser(os.path.join("~", "Downloads", "equity_names.json")))
        
    except httpx.HTTPError as e:
        print(f"API Error: {e}")
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
