import asyncio

import yfinance as yf
from curl_cffi.requests import AsyncSession


async def fetch_yahoo_price(symbol: str) -> dict:
    # 1. Быстрый неблокирующий путь: прямой async-запрос к Yahoo Chart API
    #    с жёстким таймаутом (curl_cffi имитирует браузер — без 429).
    fast = await _fetch_yahoo_price_fast(symbol)
    if fast is not None:
        return fast

    # 2. Фолбэк — yfinance. Это синхронная библиотека: если вызвать её прямо
    #    из async-обработчика, она заблокирует весь event loop uvicorn и все
    #    остальные запросы будут «вечно загружаться». Запускаем в отдельном
    #    потоке и с общим таймаутом, чтобы зависший Yahoo не держал запрос вечно.
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch_yahoo_price_sync, symbol), timeout=20)
    except asyncio.TimeoutError:
        return {"symbol": symbol, "error": "Timeout"}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def _clean_symbol(symbol: str) -> str:
    clean_symbol = symbol.strip().upper()
    if ":" in clean_symbol:
        clean_symbol = clean_symbol.split(":", 1)[1]
    return clean_symbol


async def _fetch_yahoo_price_fast(symbol: str) -> dict | None:
    """Быстрый путь: прямой запрос к quote API Yahoo с таймаутом.
    curl_cffi имитирует браузер, поэтому не получает 429 от Yahoo."""
    clean_symbol = _clean_symbol(symbol)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + clean_symbol
    try:
        async with AsyncSession(timeout=15) as session:
            resp = await session.get(url, impersonate="chrome",
                                     params={"range": "5d", "interval": "1d"})
            if resp.status_code != 200:
                return None
            data = resp.json()
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        current, previous = closes[-1], closes[-2]
        return {
            "symbol": clean_symbol,
            "price": float(current),
            "changeDay": (current / previous - 1) * 100,
            "changeValue": current - previous,
        }
    except Exception as e:
        print(f"Yahoo fast path failed for {clean_symbol}: {e}")
        return None


def _fetch_yahoo_price_sync(symbol: str) -> dict:
    clean_symbol = _clean_symbol(symbol)
    try:
        ticker = yf.Ticker(clean_symbol)
        hist = ticker.history(period="5d")
        if hist.empty or len(hist) < 2:
            return {"symbol": symbol, "error": "No data"}

        current = float(hist['Close'].iloc[-1])
        previous = float(hist['Close'].iloc[-2])
        change_pct = ((current / previous) - 1) * 100
        change_val = current - previous

        return {
            "symbol": clean_symbol,
            "price": current,
            "changeDay": change_pct,
            "changeValue": change_val
        }
    except Exception as e:
        return {"symbol": clean_symbol, "error": str(e)}
