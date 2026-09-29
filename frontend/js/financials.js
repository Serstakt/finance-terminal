// ==========================================================================
// ФИНАНСОВЫЕ ПОКАЗАТЕЛИ - МОДУЛЬ УПРАВЛЕНИЯ
// ==========================================================================

const FinancialsModule = (function() {
    // Состояние
    let state = {
        tickers: [],
        selectedTicker: null,
        periodType: 'quarterly', // 'quarterly' или 'annual'
        financialData: {} // { ticker: { periods: [...], metrics: {...} } }
    };

    // Стандартные метрики для отображения (используются как fallback,
    // если в отчете нет полной таблицы строк)
    const defaultMetrics = [
        { key: 'revenue', name: 'Выручка' },
        { key: 'gross_profit', name: 'Валовая прибыль' },
        { key: 'operating_income', name: 'Операционная прибыль' },
        { key: 'net_income', name: 'Чистая прибыль' },
        { key: 'ebitda', name: 'EBITDA' },
        { key: 'eps', name: 'EPS (прибыль на акцию)' },
        { key: 'pe_ratio', name: 'P/E Ratio' },
        { key: 'roe', name: 'ROE' },
        { key: 'debt_to_equity', name: 'Debt/Equity' },
        { key: 'current_ratio', name: 'Current Ratio' },
        { key: 'free_cash_flow', name: 'Свободный денежный поток' }
    ];

    // Форматирование числа как в smart-lab: с разделителями тысяч, без дробей
    function formatSmartNumber(value) {
        if (value === null || value === undefined) return '-';
        const numValue = parseFloat(value);
        if (isNaN(numValue)) return String(value);
        if (Math.abs(numValue - Math.round(numValue)) < 1e-9) {
            return Math.round(numValue).toLocaleString('ru-RU');
        }
        return numValue.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
    }

    // Инициализация модуля
    function init() {
        loadTickersFromStorage();
        setupEventListeners();
        renderTickerList();
        // Загружаем данные для всех тикеров из API
        loadAllFinancialDataFromAPI();
        console.log('Financials Module initialized');
    }

    // Загрузка всех данных из API
    async function loadAllFinancialDataFromAPI() {
        if (state.tickers.length === 0) return;
        
        for (const ticker of state.tickers) {
            try {
                const response = await fetch(`/api/financials/${ticker}`);
                if (response.ok) {
                    const data = await response.json();
                    
                    // Обновляем состояние данными из API
                    if (!state.financialData[ticker]) {
                        state.financialData[ticker] = {
                            quarterly: { periods: [], data: {} },
                            annual: { periods: [], data: {} }
                        };
                    }
                    
                    // Merge данных из API
                    if (data.quarterly && data.quarterly.periods) {
                        data.quarterly.periods.forEach(p => {
                            if (!state.financialData[ticker].quarterly.periods.find(ep => ep.period === p.period)) {
                                state.financialData[ticker].quarterly.periods.push(p);
                            }
                        });
                        // Merge метрик
                        Object.keys(data.quarterly.data || {}).forEach(metricKey => {
                            if (!state.financialData[ticker].quarterly.data[metricKey]) {
                                state.financialData[ticker].quarterly.data[metricKey] = {};
                            }
                            Object.assign(state.financialData[ticker].quarterly.data[metricKey], data.quarterly.data[metricKey]);
                        });
                        // Merge полной таблицы строк отчета (smart-lab style)
                        mergeRowsInto(state.financialData[ticker].quarterly, data.quarterly.rows);
                    }
                    
                    if (data.annual && data.annual.periods) {
                        data.annual.periods.forEach(p => {
                            if (!state.financialData[ticker].annual.periods.find(ep => ep.period === p.period)) {
                                state.financialData[ticker].annual.periods.push(p);
                            }
                        });
                        // Merge метрик
                        Object.keys(data.annual.data || {}).forEach(metricKey => {
                            if (!state.financialData[ticker].annual.data[metricKey]) {
                                state.financialData[ticker].annual.data[metricKey] = {};
                            }
                            Object.assign(state.financialData[ticker].annual.data[metricKey], data.annual.data[metricKey]);
                        });
                        // Merge полной таблицы строк отчета (smart-lab style)
                        mergeRowsInto(state.financialData[ticker].annual, data.annual.rows);
                    }
                }
            } catch (error) {
                console.error(`Ошибка загрузки данных для ${ticker}:`, error);
            }
        }
        
        saveFinancialDataToStorage();
        if (state.selectedTicker) {
            renderFinancialTable();
        }
    }

    // Слияние строк полной таблицы отчета в состояние
    function mergeRowsInto(target, rows) {
        if (!rows) return;
        if (!target.rows) target.rows = {};
        Object.keys(rows).forEach(name => {
            target.rows[name] = Object.assign({}, target.rows[name] || {}, rows[name]);
        });
    }

    // Загрузка тикеров из localStorage
    function loadTickersFromStorage() {
        const stored = localStorage.getItem('financials_tickers');
        if (stored) {
            try {
                state.tickers = JSON.parse(stored);
            } catch (e) {
                state.tickers = [];
            }
        }
        
        // Загрузка финансовых данных
        const storedData = localStorage.getItem('financials_data');
        if (storedData) {
            try {
                state.financialData = JSON.parse(storedData);
            } catch (e) {
                state.financialData = {};
            }
        }
    }

    // Сохранение тикеров в localStorage
    function saveTickersToStorage() {
        localStorage.setItem('financials_tickers', JSON.stringify(state.tickers));
    }

    // Сохранение финансовых данных
    function saveFinancialDataToStorage() {
        localStorage.setItem('financials_data', JSON.stringify(state.financialData));
    }

    // Настройка обработчиков событий
    function setupEventListeners() {
        // Добавление тикера
        const addBtn = document.getElementById('financials-add-ticker-btn');
        const searchInput = document.getElementById('financials-search-input');
        
        if (addBtn) {
            addBtn.addEventListener('click', addTicker);
        }
        
        if (searchInput) {
            searchInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    addTicker();
                }
            });
        }
    }

    // Добавление тикера
    function addTicker() {
        const input = document.getElementById('financials-search-input');
        const ticker = input.value.trim().toUpperCase();
        
        if (!ticker) {
            alert('Введите тикер');
            return;
        }
        
        if (state.tickers.includes(ticker)) {
            alert('Этот тикер уже добавлен');
            return;
        }
        
        state.tickers.push(ticker);
        saveTickersToStorage();
        renderTickerList();
        input.value = '';
        
        // Инициализируем пустые данные для тикера если их нет
        if (!state.financialData[ticker]) {
            state.financialData[ticker] = {
                quarterly: { periods: [], data: {} },
                annual: { periods: [], data: {} }
            };
            saveFinancialDataToStorage();
        }
    }

    // Удаление тикера
    function removeTicker(ticker, event) {
        event.stopPropagation();
        
        if (!confirm(`Удалить тикер ${ticker}?`)) {
            return;
        }
        
        state.tickers = state.tickers.filter(t => t !== ticker);
        if (state.selectedTicker === ticker) {
            state.selectedTicker = null;
        }
        saveTickersToStorage();
        renderTickerList();
    }

    // Выбор тикера
    function selectTicker(ticker) {
        state.selectedTicker = ticker;
        renderTickerList();
        updateSelectedLabel();
        renderFinancialTable();
    }

    // Обновление метки выбранного тикера
    function updateSelectedLabel() {
        const label = document.getElementById('selected-ticker-label');
        if (label) {
            label.textContent = state.selectedTicker || 'Выберите тикер';
        }
    }

    // Отрисовка списка тикеров
    function renderTickerList() {
        const container = document.getElementById('financials-ticker-list');
        if (!container) return;
        
        if (state.tickers.length === 0) {
            container.innerHTML = '<div class="empty-state">Список пуст. Добавьте тикеры для анализа.</div>';
            return;
        }
        
        container.innerHTML = state.tickers.map(ticker => `
            <div class="financials-ticker-item ${state.selectedTicker === ticker ? 'active' : ''}" 
                 onclick="FinancialsModule.selectTicker('${ticker}')">
                <span class="ticker-name">${ticker}</span>
                <button class="ticker-remove" onclick="FinancialsModule.removeTicker('${ticker}', event)" title="Удалить">×</button>
            </div>
        `).join('');
    }

    // Переключение периода (кварталы/годы)
    function setPeriodType(periodType) {
        state.periodType = periodType;
        
        // Обновляем активную кнопку
        document.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.period === periodType);
        });
        
        renderFinancialTable();
    }

    // Отрисовка таблицы финансовых показателей (в стиле smart-lab: все строки отчета)
    function renderFinancialTable() {
        const headerRow = document.getElementById('financials-table-header');
        const tbody = document.getElementById('financials-table-body');
        
        if (!headerRow || !tbody) return;
        
        if (!state.selectedTicker) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Выберите тикер для отображения данных</td></tr>';
            headerRow.innerHTML = '<th>Показатель</th>';
            return;
        }
        
        const tickerData = state.financialData[state.selectedTicker];
        const periodData = tickerData ? tickerData[state.periodType] : null;
        const periods = periodData ? periodData.periods : [];
        const rawRows = (periodData && periodData.rows) ? periodData.rows : {};
        const rowNames = Object.keys(rawRows);

        // Полная таблица всех строк отчета (smart-lab style), если есть данные
        if (rowNames.length > 0) {
            // Собираем все колонки-периоды из строк + периоды загруженных отчетов
            const colSet = new Set();
            rowNames.forEach(name => Object.keys(rawRows[name]).forEach(c => colSet.add(c)));
            let columns = Array.from(colSet).sort(comparePeriodLabels).reverse();
            const displayColumns = columns.slice(0, 5); // последние 5 периодов/лет

            headerRow.innerHTML = '<th>Показатель</th>' + displayColumns.map(c => `
                <th>
                    <div>${escapeHtml(c)}</div>
                </th>
            `).join('');

            tbody.innerHTML = rowNames.map(name => {
                const cells = displayColumns.map(col => {
                    const v = rawRows[name][col];
                    if (v === undefined || v === null) return '<td class="num-cell">-</td>';
                    const neg = parseFloat(v) < 0 ? ' negative' : '';
                    return `<td class="num-cell${neg}">${formatSmartNumber(v)}</td>`;
                }).join('');
                return `<tr><td class="metric-name" title="${escapeHtml(name)}">${escapeHtml(name)}</td>${cells}</tr>`;
            }).join('');
            return;
        }
        
        // Fallback: стандартные метрики
        const metricsData = periodData ? periodData.data : {};
        
        if (!periods || periods.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Нет данных за ${state.periodType === 'quarterly' ? 'кварталы' : 'годы'}. Загрузите отчетность.</td></tr>`;
            
            // Заголовок только с первым столбцом
            headerRow.innerHTML = '<th>Показатель</th>';
            for (let i = 0; i < 5; i++) {
                headerRow.innerHTML += `<th>-</th>`;
            }
            return;
        }
        
        // Берем последние 5 периодов
        const displayPeriods = periods.slice(-5);
        
        // Рендерим заголовок
        headerRow.innerHTML = '<th>Показатель</th>' + displayPeriods.map(p => `
            <th>
                <div>${p.period}</div>
                <div class="period-header">${p.endDate || ''}</div>
            </th>
        `).join('');
        
        // Рендерим строки с метриками
        tbody.innerHTML = defaultMetrics.map(metric => {
            const values = displayPeriods.map(period => {
                const value = metricsData[metric.key] ? metricsData[metric.key][period.period] : null;
                return value !== null && value !== undefined ? formatMetricValue(metric.key, value) : '-';
            });
            
            return `
                <tr>
                    <td class="metric-name">${metric.name}</td>
                    ${values.map(v => `<td>${v}</td>`).join('')}
                </tr>
            `;
        }).join('');
    }

    // Сравнение меток периодов ('2025-03-31', 'Q1 2025', '2024')
    function comparePeriodLabels(a, b) {
        return periodSortKey(a) - periodSortKey(b);
    }

    function periodSortKey(label) {
        let m = label.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (m) return (parseInt(m[1]) * 12 + parseInt(m[2])) * 10;
        m = label.match(/^Q(\d)\s+(\d{4})$/);
        if (m) return parseInt(m[2]) * 12 + parseInt(m[1]) * 3;
        m = label.match(/^(\d{4})$/);
        if (m) return parseInt(m[1]) * 12 + 12;
        return 0;
    }

    function escapeHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // Форматирование значения метрики
    function formatMetricValue(key, value) {
        if (value === null || value === undefined) return '-';
        
        const numValue = parseFloat(value);
        if (isNaN(numValue)) return value;
        
        // Проценты
        if (['roe', 'debt_to_equity', 'current_ratio'].includes(key)) {
            return numValue.toFixed(2) + (key === 'roe' || key === 'debt_to_equity' ? '%' : 'x');
        }
        
        // Большие числа (выручка, прибыль и т.д.)
        if (Math.abs(numValue) >= 1e9) {
            return (numValue / 1e9).toFixed(2) + 'B';
        }
        if (Math.abs(numValue) >= 1e6) {
            return (numValue / 1e6).toFixed(2) + 'M';
        }
        
        return numValue.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Получение данных для API
    function getFinancialData(ticker) {
        return state.financialData[ticker] || null;
    }

    // Обновление данных из API (после загрузки отчета)
    function updateFinancialData(ticker, periodType, period, endDate, metrics, rawTable) {
        if (!state.financialData[ticker]) {
            state.financialData[ticker] = {
                quarterly: { periods: [], data: {} },
                annual: { periods: [], data: {} }
            };
        }
        
        const targetData = state.financialData[ticker][periodType];

        // Полная таблица строк отчета (smart-lab style)
        if (rawTable && Array.isArray(rawTable.rows)) {
            if (!targetData.rows) targetData.rows = {};
            rawTable.rows.forEach(row => {
                if (!row.name) return;
                targetData.rows[row.name] = Object.assign(
                    {}, targetData.rows[row.name] || {}, row.values || {}
                );
            });
        }
        
        // Проверяем, есть ли уже такой период
        const existingIndex = targetData.periods.findIndex(p => p.period === period);
        
        if (existingIndex >= 0) {
            // Обновляем существующий период
            targetData.periods[existingIndex] = { period, endDate };
        } else {
            // Добавляем новый период
            targetData.periods.push({ period, endDate });
            // Сортируем периоды
            targetData.periods.sort((a, b) => {
                if (periodType === 'quarterly') {
                    // Сортировка кварталов вида "Q1 2024"
                    const parseQuarter = (p) => {
                        const match = p.match(/Q(\d+)\s+(\d+)/);
                        if (match) {
                            return parseInt(match[2]) * 10 + parseInt(match[1]);
                        }
                        return 0;
                    };
                    return parseQuarter(a.period) - parseQuarter(b.period);
                } else {
                    // Сортировка годов
                    return parseInt(a.period) - parseInt(b.period);
                }
            });
        }
        
        // Обновляем данные по метрикам
        Object.keys(metrics).forEach(key => {
            if (!targetData.data[key]) {
                targetData.data[key] = {};
            }
            targetData.data[key][period] = metrics[key];
        });
        
        saveFinancialDataToStorage();
        renderFinancialTable();
    }

    // Экспорт состояния для использования извне
    return {
        init,
        addTicker,
        removeTicker,
        selectTicker,
        setPeriodType,
        renderTickerList,
        renderFinancialTable,
        updateFinancialData,
        getFinancialData,
        getState: () => state
    };
})();

// Глобальные функции для HTML
function setFinancialPeriod(periodType) {
    FinancialsModule.setPeriodType(periodType);
}

function selectTicker(ticker) {
    FinancialsModule.selectTicker(ticker);
}

function removeTicker(ticker, event) {
    FinancialsModule.removeTicker(ticker, event);
}

function openUploadReportModal() {
    const modal = document.getElementById('upload-report-modal');
    const select = document.getElementById('report-ticker-select');
    
    // Заполняем селект тикерами
    const tickers = FinancialsModule.getState().tickers;
    if (tickers.length === 0) {
        alert('Сначала добавьте тикеры в список');
        return;
    }
    
    select.innerHTML = tickers.map(t => `<option value="${t}">${t}</option>`).join('');
    
    if (modal) {
        modal.style.display = 'flex';
    }
}

function closeUploadReportModal() {
    const modal = document.getElementById('upload-report-modal');
    if (modal) {
        modal.style.display = 'none';
    }
    // Очищаем инпут файла
    const fileInput = document.getElementById('report-file-input');
    if (fileInput) {
        fileInput.value = '';
    }
}

async function uploadReportFile() {
    const tickerSelect = document.getElementById('report-ticker-select');
    const periodTypeSelect = document.getElementById('report-period-type');
    const fileInput = document.getElementById('report-file-input');
    
    const ticker = tickerSelect.value;
    const periodType = periodTypeSelect.value;
    const file = fileInput.files[0];
    
    if (!file) {
        alert('Выберите файл для загрузки');
        return;
    }
    
    // Создаем FormData для отправки файла
    const formData = new FormData();
    formData.append('file', file);
    formData.append('ticker', ticker);
    formData.append('period_type', periodType);
    
    try {
        // Отправляем файл на бэкенд
        const response = await fetch('/api/financials/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Ошибка загрузки: ' + response.statusText);
        }
        
        const result = await response.json();
        
        if (result.status === 'ok') {
            // Обновляем данные в интерфейсе (включая полную таблицу строк отчета)
            FinancialsModule.updateFinancialData(
                ticker,
                result.period_type || periodType,
                result.period,
                result.end_date,
                result.metrics,
                result.raw_table
            );

            alert(`Отчетность успешно загружена! Извлечено строк: ${result.rows_count || 0} за период ${result.period}.`);
            closeUploadReportModal();

            // Если этот тикер выбран, переключаемся на его тип периода и обновляем таблицу
            if (FinancialsModule.getState().selectedTicker === ticker) {
                if ((result.period_type || periodType) !== FinancialsModule.getState().periodType) {
                    FinancialsModule.setPeriodType(result.period_type || periodType);
                } else {
                    FinancialsModule.renderFinancialTable();
                }
            }
        } else {
            throw new Error(result.message || 'Ошибка обработки');
        }
    } catch (error) {
        console.error('Ошибка загрузки отчета:', error);
        alert('Ошибка при загрузке отчета: ' + error.message);
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    FinancialsModule.init();
});
