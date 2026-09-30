import asyncio
import yfinance as yf


async def fetch_yahoo_price(symbol: str) -> dict:
    # yfinance — синхронная библиотека (blockingly делает HTTP-запросы).
    # Если вызвать её прямо из async-обработчика, она заблокирует весь
    # event loop uvicorn и все остальные запросы "вечно загружаются".
    # Поэтому запускать её нужно в отдельном потоке.
    try:
        return await asyncio.to_thread(_fetch_yahoo_price_sync, symbol)
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


def _fetch_yahoo_price_sync(symbol: str) -> dict:
    try:
        # Нормализуем тикер: "NASDAQ:AAPL" -> "AAPL" (Yahoo не понимает префиксы бирж)
        clean_symbol = symbol.strip().upper()
        if ":" in clean_symbol:
            clean_symbol = clean_symbol.split(":", 1)[1]

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
