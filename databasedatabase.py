"""
database/database.py

SQLite Database Manager
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import DateTime
from sqlalchemy import Boolean
from datetime import datetime

# ---------------------------------------------------
# Database Path
# ---------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "trade.db"

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


# ---------------------------------------------------
# Position Table
# ---------------------------------------------------

class Position(Base):

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)

    exchange = Column(String)

    symbol = Column(String)

    side = Column(String)

    quantity = Column(Float)

    entry_price = Column(Float)

    current_price = Column(Float)

    tp_price = Column(Float)

    sl_price = Column(Float)

    trailing_price = Column(Float)

    status = Column(String, default="OPEN")

    created_at = Column(DateTime, default=datetime.utcnow)

    closed_at = Column(DateTime)


# ---------------------------------------------------
# Trade History
# ---------------------------------------------------

class TradeHistory(Base):

    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True)

    exchange = Column(String)

    symbol = Column(String)

    side = Column(String)

    quantity = Column(Float)

    entry_price = Column(Float)

    exit_price = Column(Float)

    pnl = Column(Float)

    pnl_percent = Column(Float)

    reason = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------
# Signals
# ---------------------------------------------------

class Signal(Base):

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)

    exchange = Column(String)

    symbol = Column(String)

    signal = Column(String)

    confidence = Column(Float)

    strategy = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------
# Orders
# ---------------------------------------------------

class Order(Base):

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)

    exchange = Column(String)

    symbol = Column(String)

    order_id = Column(String)

    side = Column(String)

    order_type = Column(String)

    quantity = Column(Float)

    price = Column(Float)

    status = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------
# Risk Log
# ---------------------------------------------------

class RiskLog(Base):

    __tablename__ = "risk_log"

    id = Column(Integer, primary_key=True)

    symbol = Column(String)

    reason = Column(String)

    message = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------
# Settings
# ---------------------------------------------------

class Setting(Base):

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)

    key = Column(String, unique=True)

    value = Column(String)


# ---------------------------------------------------
# Database Functions
# ---------------------------------------------------

def init_database():

    Base.metadata.create_all(engine)


def get_session():

    return SessionLocal()


# ---------------------------------------------------
# CRUD
# ---------------------------------------------------

def add_position(position):

    session = get_session()

    session.add(position)

    session.commit()

    session.refresh(position)

    session.close()

    return position


def update_position(position):

    session = get_session()

    session.merge(position)

    session.commit()

    session.close()


def delete_position(position):

    session = get_session()

    session.delete(position)

    session.commit()

    session.close()


def get_open_positions():

    session = get_session()

    positions = (
        session.query(Position)
        .filter(Position.status == "OPEN")
        .all()
    )

    session.close()

    return positions


def add_trade(history):

    session = get_session()

    session.add(history)

    session.commit()

    session.close()


def add_signal(signal):

    session = get_session()

    session.add(signal)

    session.commit()

    session.close()


def add_order(order):

    session = get_session()

    session.add(order)

    session.commit()

    session.close()


def add_risk_log(log):

    session = get_session()

    session.add(log)

    session.commit()

    session.close()


# ---------------------------------------------------
# Initialize
# ---------------------------------------------------

if __name__ == "__main__":

    init_database()

    print("Database initialized.")