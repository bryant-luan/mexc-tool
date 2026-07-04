"""
exchange/mexc.py

MEXC Spot Exchange
Based on CCXT

Author: ChatGPT
"""

from __future__ import annotations

import time
import logging
from typing import Dict
from typing import List
from typing import Optional

import ccxt

from exchange.base import (
    BaseExchange,
    ExchangeException,
    AuthenticationError,
    NetworkException,
    OrderException,
)


class MEXCExchange(BaseExchange):

    """
    MEXC Spot Exchange
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
    ):

        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
        )

        self.logger = logging.getLogger("MEXC")

        self.exchange = ccxt.mexc(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "timeout": 30000,
            }
        )

        if testnet:

            # 預留測試網
            pass

        self.markets = {}

        self.symbol_cache = []

        self.load_markets()

    # ==================================================
    # Market Cache
    # ==================================================

    def load_markets(self):

        """
        Load all market information
        """

        try:

            self.markets = self.retry(
                self.exchange.load_markets
            )

            self.symbol_cache = list(
                self.markets.keys()
            )

            self.logger.info(
                "Loaded %s markets",
                len(self.symbol_cache),
            )

        except Exception as e:

            raise NetworkException(str(e))

    # ==================================================
    # Public
    # ==================================================

    def ping(self):

        try:

            self.exchange.fetch_time()

            return True

        except Exception:

            return False

    def get_symbols(self) -> List[str]:

        return self.symbol_cache

    def get_exchange_info(self):

        return self.markets

    def get_symbol_info(
        self,
        symbol: str,
    ):

        if symbol not in self.markets:

            raise ExchangeException(
                f"Unknown Symbol : {symbol}"
            )

        return self.markets[symbol]

    # ==================================================
    # Precision
    # ==================================================

    def amount_precision(
        self,
        symbol: str,
    ) -> int:

        market = self.get_symbol_info(symbol)

        return market["precision"]["amount"]

    def price_precision(
        self,
        symbol: str,
    ) -> int:

        market = self.get_symbol_info(symbol)

        return market["precision"]["price"]

    def format_amount(
        self,
        symbol: str,
        amount: float,
    ) -> float:

        return float(
            self.exchange.amount_to_precision(
                symbol,
                amount,
            )
        )

    def format_price(
        self,
        symbol: str,
        price: float,
    ) -> float:

        return float(
            self.exchange.price_to_precision(
                symbol,
                price,
            )
        )

    # ==================================================
    # Retry Wrapper
    # ==================================================

    def safe_call(
        self,
        func,
        *args,
        **kwargs,
    ):

        try:

            return self.retry(
                func,
                *args,
                **kwargs,
            )

        except ccxt.AuthenticationError as e:

            raise AuthenticationError(str(e))

        except ccxt.NetworkError as e:

            raise NetworkException(str(e))

        except ccxt.ExchangeError as e:

            raise ExchangeException(str(e))

        except Exception as e:

            raise ExchangeException(str(e))