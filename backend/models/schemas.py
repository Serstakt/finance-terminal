from pydantic import BaseModel
from typing import Dict, Any, Optional, List


class PriceResponse(BaseModel):
    symbol: str
    price: float | None = None
    changeDay: float | None = None
    changeValue: float | None = None
    changeWeek: float | None = None
    changeMonth: float | None = None
    changeYear: float | None = None


class PositionCreate(BaseModel):
    symbol: str
    quantity: float
    avg_price: float
    sector: str = "Не указан"


class FinancialDataUpload(BaseModel):
    ticker: str
    period_type: str  # 'quarterly' или 'annual'
    period: str  # например 'Q1 2024' или '2024'
    end_date: Optional[str] = None
    metrics: Dict[str, Any]


class FinancialMetrics(BaseModel):
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    ebitda: Optional[float] = None
    eps: Optional[float] = None
    pe_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    free_cash_flow: Optional[float] = None


class FinancialPeriod(BaseModel):
    period: str
    end_date: Optional[str] = None


class FinancialDataResponse(BaseModel):
    ticker: str
    quarterly: Optional[Dict[str, Any]] = None
    annual: Optional[Dict[str, Any]] = None
