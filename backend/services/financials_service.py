from sqlalchemy import Column, String, Text, DateTime, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import json
from backend.database.database import Base, SessionLocal, engine


class FinancialReport(Base):
    __tablename__ = 'financial_reports'
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True, nullable=False)
    period_type = Column(String, nullable=False)  # 'quarterly' или 'annual'
    period = Column(String, nullable=False)  # например 'Q1 2024' или '2024'
    end_date = Column(String, nullable=True)  # дата окончания периода
    metrics_json = Column(Text, nullable=False)  # JSON с метриками
    raw_json = Column(Text, nullable=True)  # JSON: полная таблица всех строк отчета
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Создаем таблицу
Base.metadata.create_all(bind=engine)


def _migrate_add_raw_column():
    """Добавляет колонку raw_json в существующую БД (SQLite), если её нет."""
    try:
        from sqlalchemy import inspect, text
        insp = inspect(engine)
        if 'financial_reports' in insp.get_table_names():
            cols = {c['name'] for c in insp.get_columns('financial_reports')}
            if 'raw_json' not in cols:
                with engine.begin() as conn:
                    conn.execute(text(
                        "ALTER TABLE financial_reports ADD COLUMN raw_json TEXT"
                    ))
    except Exception as e:
        print(f"[financials] миграция raw_json пропущена: {e}")


_migrate_add_raw_column()


async def save_financial_data(ticker: str, period_type: str, period: str, 
                               end_date: str, metrics: dict, raw_table: dict = None) -> dict:
    """Сохраняет финансовые данные (включая полную таблицу строк отчета) в БД"""
    db = SessionLocal()
    try:
        # Проверяем, есть ли уже такая запись
        existing = db.query(FinancialReport).filter_by(
            ticker=ticker,
            period_type=period_type,
            period=period
        ).first()
        
        if existing:
            # Обновляем существующую запись
            existing.metrics_json = json.dumps(metrics)
            existing.end_date = end_date
            if raw_table is not None:
                existing.raw_json = json.dumps(raw_table, ensure_ascii=False)
            existing.updated_at = datetime.utcnow()
        else:
            # Создаем новую запись
            report = FinancialReport(
                ticker=ticker,
                period_type=period_type,
                period=period,
                end_date=end_date,
                metrics_json=json.dumps(metrics),
                raw_json=json.dumps(raw_table, ensure_ascii=False) if raw_table is not None else None
            )
            db.add(report)
        
        db.commit()
        
        return {
            "status": "ok",
            "ticker": ticker,
            "period_type": period_type,
            "period": period,
            "end_date": end_date,
            "metrics": metrics
        }
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        db.close()


async def get_financial_data(ticker: str, period_type: str = None) -> dict:
    """Получает финансовые данные для тикера"""
    db = SessionLocal()
    try:
        query = db.query(FinancialReport).filter_by(ticker=ticker)
        
        if period_type:
            query = query.filter_by(period_type=period_type)
        
        reports = query.order_by(FinancialReport.created_at.desc()).all()
        
        result = {
            "ticker": ticker,
            "quarterly": {"periods": [], "data": {}, "rows": {}},
            "annual": {"periods": [], "data": {}, "rows": {}}
        }
        
        for report in reports:
            metrics = json.loads(report.metrics_json)
            period_data = {
                "period": report.period,
                "end_date": report.end_date
            }
            
            # Добавляем период в список
            result[report.period_type]["periods"].append(period_data)
            
            # Добавляем метрики
            for key, value in metrics.items():
                if key not in result[report.period_type]["data"]:
                    result[report.period_type]["data"][key] = {}
                result[report.period_type]["data"][key][report.period] = value

            # Добавляем полную таблицу строк отчета (smart-lab style)
            if report.raw_json:
                try:
                    raw = json.loads(report.raw_json)
                    bucket = result[report.period_type].setdefault("rows", {})
                    for row in raw.get("rows", []):
                        name = row.get("name")
                        if not name:
                            continue
                        target = bucket.setdefault(name, {})
                        for col, val in (row.get("values") or {}).items():
                            target[col] = val
                except Exception:
                    pass
        
        # Сортируем периоды
        for ptype in ["quarterly", "annual"]:
            periods = result[ptype]["periods"]
            if ptype == "quarterly":
                # Сортировка кварталов
                import re
                def parse_quarter(p):
                    match = re.match(r'Q(\d+)\s+(\d+)', p.get("period", ""))
                    if match:
                        return int(match.group(2)) * 10 + int(match.group(1))
                    return 0
                periods.sort(key=lambda x: parse_quarter(x))
            else:
                # Сортировка годов
                periods.sort(key=lambda x: int(x.get("period", "0")))
        
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        db.close()


async def delete_financial_data(ticker: str, period_type: str, period: str) -> dict:
    """Удаляет финансовые данные"""
    db = SessionLocal()
    try:
        report = db.query(FinancialReport).filter_by(
            ticker=ticker,
            period_type=period_type,
            period=period
        ).first()
        
        if report:
            db.delete(report)
            db.commit()
            return {"status": "ok"}
        else:
            return {"status": "error", "message": "Запись не найдена"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


async def process_report_with_llm(file_content: bytes, file_type: str, 
                                   ticker: str, period_type: str) -> dict:
    """
    Обрабатывает файл с отчетностью: читает ВСЕ строки отчета (Excel/CSV/PDF/DOCX/HTML),
    строит полную таблицу по аналогии со smart-lab.ru, при наличии LLM_API_KEY —
    обогащает данные через LLM (нормализация названий, определение периода).
    """
    from . import report_parser

    result = await report_parser.parse_report_file(
        filename=f"report.{file_type}",
        content=file_content,
        ticker=ticker,
    )

    raw_table = result["raw_table"]
    if not raw_table["rows"]:
        raise ValueError(
            "Не удалось извлечь ни одной строки из файла. "
            "Поддерживаются Excel (.xlsx), CSV, PDF, DOCX, HTML с табличными данными."
        )

    # Ключевые метрики для совместимости со старым представлением данных
    key_map = {
        "revenue": ("выручка",),
        "gross_profit": ("валовая прибыль",),
        "operating_income": ("операционная прибыль", "прибыль от продаж"),
        "net_income": ("чистая прибыль",),
        "ebitda": ("ebitda",),
    }
    metrics = {}
    period = result["period"]
    for m_key, patterns in key_map.items():
        for row in raw_table["rows"]:
            name_l = row["name"].lower()
            if any(p in name_l for p in patterns):
                val = row["values"].get(period)
                if val is None and row["values"]:
                    val = next(iter(row["values"].values()))
                if val is not None:
                    metrics[m_key] = val
                break

    return {
        "period": period,
        "end_date": result["end_date"],
        "period_type": result.get("period_type") or period_type,
        "metrics": metrics,
        "raw_table": raw_table,
        "rows_count": len(raw_table["rows"]),
    }
