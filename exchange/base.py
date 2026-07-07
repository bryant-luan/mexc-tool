"""
exchange/base.py

Base Exchange Interface

所有交易所(MEXC / Gate.io / Binance...)皆繼承此類別
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging
import time


class ExchangeException(Exception):
    """交易所錯誤"""


class AuthenticationError(ExchangeException):
    """API 驗證失敗"""


class OrderException(ExchangeException):
    """訂單錯誤"""


class NetworkException(ExchangeException):
    """網路錯誤"""


class BaseExchange(ABC):
    """
    所有交易所的共同介面
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
    ):

        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

        self.logger = logging.getLogger(self.__class__.__name__)

        self.max_retry = 3

        self.retry_delay = 1

    # ==================================================
    # Retry Wrapper
    # ==================================================

    def retry(self, func, *args, **kwargs):

        last_exception = None

        for i in range(self.max_retry):

            try:

                return func(*args, **kwargs)

            except Exception as e:

                last_exception = e

                self.logger.warning(
                    f"Retry {i+1}/{self.max_retry} : {e}"
                )

                time.sleep(self.retry_delay)

        raise last_exception

    # ==================================================
    # Market
    # ==================================================

    @abstractmethod
    def get_symbols(self) -> List[str]:
        """
        取得所有交易對
        """
        pass

    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """
        最新價格
        """
        pass

    @abstractmethod
    def get_ticker(self, symbol: str) -> Dict:
        """
        Ticker資訊
        """
        pass

    @abstractmethod
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
    ):
        """
        K線資料
        """
        pass

    # ==================================================
    # Account
    # ==================================================

    @abstractmethod
    def get_balance(self):
        """
        帳戶餘額
        """
        pass

    @abstractmethod
    def get_positions(self):
        """
        持倉
        """
        pass

    @abstractmethod
    def get_open_orders(self):
        """
        未成交訂單
        """
        pass

    # ==================================================
    # Orders
    # ==================================================

    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ):
        """
        市價單
        """
        pass

    @abstractmethod
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
    ):
        """
        限價單
        """
        pass

    @abstractmethod
    def cancel_order(
        self,
        order_id: str,
        symbol: str,
    ):
        """
        取消訂單
        """
        pass

    @abstractmethod
    def get_order(
        self,
        order_id: str,
        symbol: str,
    ):
        """
        查詢訂單
        """
        pass

    # ==================================================
    # TP / SL
    # ==================================================

    def market_buy(
        self,
        symbol: str,
        quantity: float,
    ):
        return self.place_market_order(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
        )

    def market_sell(
        self,
        symbol: str,
        quantity: float,
    ):
        return self.place_market_order(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
        )

    def limit_buy(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ):
        return self.place_limit_order(
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=price,
        )

    def limit_sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ):
        return self.place_limit_order(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            price=price,
        )

    # ==================================================
    # Precision
    # ==================================================

    def round_quantity(
        self,
        quantity: float,
        precision: int,
    ) -> float:

        return round(quantity, precision)

    def round_price(
        self,
        price: float,
        precision: int,
    ) -> float:

        return round(price, precision)

    # ==================================================
    # Utils
    # ==================================================

    def validate_side(self, side: str):

        side = side.upper()

        if side not in ["BUY", "SELL"]:

            raise ValueError("Side 必須是 BUY 或 SELL")

        return side

    def validate_quantity(self, quantity: float):

        if quantity <= 0:

            raise ValueError("Quantity 必須大於0")

        return quantity

    def validate_price(self, price: float):

        if price <= 0:

            raise ValueError("Price 必須大於0")

        return price

    # ==================================================
    # Health Check
    # ==================================================

    @abstractmethod
    def ping(self):
        """
        API是否正常
        """
        pass

    # ==================================================
    # Exchange Info
    # ==================================================

    @abstractmethod
    def get_exchange_info(self):
        """
        交易所資訊
        """
        pass

    @abstractmethod
    def get_symbol_info(
        self,
        symbol: str,
    ):
        """
        幣種資訊
        """
        pass

    # ==================================================
    # Close
    # ==================================================

    def close(self):

        self.logger.info(
            f"{self.__class__.__name__} Closed."
        )