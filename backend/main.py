from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import asyncio

from .services import moex_service, yahoo_service, crypto_service, telegram_news_service
from .services import portfolio_service
from .services import financials_service
from .models import schemas

app = FastAPI(title="Financial Terminal API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Путь к фронтенду
FRONTEND_PATH = Path(__file__).parent.parent / "frontend"

# Раздаем статику (CSS, JS) напрямую
app.mount("/css", StaticFiles(directory=FRONTEND_PATH / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_PATH / "js"), name="js")


# Главная страница
@app.get("/")
async def root():
    return FileResponse(FRONTEND_PATH / "index.html")


# API endpoints
@app.get("/api/prices/{symbol}", response_model=schemas.PriceResponse)
async def get_price(symbol: str):
    try:
        if symbol.startswith("MOEX:"):
            return await moex_service.fetch_moex_price(symbol.replace("MOEX:", ""))
        elif symbol.startswith(("NASDAQ:", "NYSE:")):
            return await yahoo_service.fetch_yahoo_price(symbol)
        elif symbol.startswith("BINANCE:"):
            return await crypto_service.fetch_crypto_price(symbol.replace("BINANCE:", ""))
        else:
            return await yahoo_service.fetch_yahoo_price(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/portfolio")
async def get_portfolio():
    return await portfolio_service.get_portfolio_with_pnl()


@app.post("/api/portfolio")
async def add_position_endpoint(position: schemas.PositionCreate):
    sector = getattr(position, 'sector', 'Не указан')
    return await portfolio_service.add_position(
        position.symbol,
        position.quantity,
        position.avg_price,
        sector
    )


@app.delete("/api/portfolio/{symbol}")
async def remove_position_endpoint(symbol: str):
    return await portfolio_service.remove_position(symbol)


@app.get("/api/news/telegram/{ticker}")
async def get_telegram_news(ticker: str, force_refresh: bool = Query(default=False)):
    """Новости из @newssmartlab по тикеру"""
    clean_ticker = ticker.replace("MOEX:", "").upper()

    # Передаем флаг force_refresh в сервис
    news = await telegram_news_service.fetch_smartlab_telegram_news(
        clean_ticker,
        force_refresh=force_refresh
    )
    return {"symbol": f"MOEX:{clean_ticker}", "news": news}


# =============================================================================
# ФИНАНСОВЫЕ ПОКАЗАТЕЛИ - API ENDPOINTS
# =============================================================================

@app.post("/api/financials/upload")
async def upload_financial_report(
    file: UploadFile = File(...),
    ticker: str = Form(...),
    period_type: str = Form(...)
):
    """
    Загружает файл с финансовой отчетностью и обрабатывает его с помощью LLM.
    Извлеченные данные сохраняются в БД.
    """
    try:
        # Читаем содержимое файла
        file_content = await file.read()
        file_type = file.filename.split('.')[-1].lower() if '.' in file.filename else 'unknown'
        
        # Обрабатываем файл: читаем все строки отчетности (+ LLM при наличии ключа)
        llm_result = await financials_service.process_report_with_llm(
            file_content=file_content,
            file_type=file_type,
            ticker=ticker,
            period_type=period_type
        )

        actual_period_type = llm_result.get("period_type") or period_type
        
        # Сохраняем данные (включая полную таблицу строк) в БД
        save_result = await financials_service.save_financial_data(
            ticker=ticker,
            period_type=actual_period_type,
            period=llm_result["period"],
            end_date=llm_result["end_date"],
            metrics=llm_result["metrics"],
            raw_table=llm_result.get("raw_table")
        )
        
        if save_result.get("status") == "error":
            raise HTTPException(status_code=500, detail=save_result.get("message", "Ошибка сохранения"))
        
        return {
            "status": "ok",
            "ticker": ticker,
            "period": llm_result["period"],
            "period_type": actual_period_type,
            "end_date": llm_result["end_date"],
            "metrics": llm_result["metrics"],
            "raw_table": llm_result.get("raw_table"),
            "rows_count": llm_result.get("rows_count", 0)
        }
        
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/financials/{ticker}")
async def get_financial_data(ticker: str, period_type: str = None):
    """Получает финансовые данные для тикера"""
    result = await financials_service.get_financial_data(ticker, period_type)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "Ошибка получения данных"))
    
    return result


@app.delete("/api/financials/{ticker}/{period_type}/{period}")
async def delete_financial_data(ticker: str, period_type: str, period: str):
    """Удаляет финансовые данные за указанный период"""
    result = await financials_service.delete_financial_data(ticker, period_type, period)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Данные не найдены"))
    
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
