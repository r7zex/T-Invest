"""
Модуль для генерации графиков динамики баланса и стоимости акций.
"""
import matplotlib
matplotlib.use('Agg')  # Использование non-GUI backend для серверных приложений

import io
import logging
from datetime import datetime
from typing import List, Dict, Tuple
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

logger = logging.getLogger(__name__)


def format_currency(value: float, currency: str = "RUB") -> str:
    """
    Форматирует значение в валюту.
    
    Args:
        value: Числовое значение
        currency: Код валюты
        
    Returns:
        str: Отформатированная строка
    """
    currency_symbols = {
        "RUB": "₽",
        "USD": "$",
        "EUR": "€",
        "rub": "₽",
        "usd": "$",
        "eur": "€"
    }
    symbol = currency_symbols.get(currency, currency)
    return f"{value:,.0f}{symbol}"


def _find_trend_segments(timestamps: List[datetime], values: List[float]) -> List[Tuple[int, int]]:
    """
    Определяет сегменты тренда на графике.
    
    Алгоритм находит точки разворота тренда используя скользящее окно
    и изменение направления движения цены.
    
    Args:
        timestamps: Список временных меток
        values: Список значений
        
    Returns:
        List[Tuple[int, int]]: Список сегментов в виде (начало, конец)
    """
    if len(values) < 2:
        return []
    
    if len(values) < 3:
        return [(0, len(values) - 1)]
    
    segments = []
    window_size = max(3, len(values) // 10)  # Размер окна для определения тренда
    
    start_idx = 0
    current_trend = None  # None, 'up', 'down'
    
    for i in range(1, len(values)):
        # Определяем локальный тренд
        if i < window_size:
            local_values = values[:i+1]
        else:
            local_values = values[i-window_size:i+1]
        
        # Линейная регрессия для определения направления
        if len(local_values) >= 2:
            # Защита от деления на ноль
            value_diff = local_values[-1] - local_values[0]
            avg_change = value_diff / len(local_values) if len(local_values) > 0 else 0
            new_trend = 'up' if avg_change > 0 else 'down'
            
            # Если тренд изменился, создаем новый сегмент
            if current_trend is not None and new_trend != current_trend and i - start_idx > window_size:
                segments.append((start_idx, i - 1))
                start_idx = i - 1
            
            current_trend = new_trend
    
    # Добавляем последний сегмент
    if start_idx < len(values):
        segments.append((start_idx, len(values) - 1))
    
    # Если сегментов получилось слишком много, объединяем короткие
    if len(segments) > 5:
        return [(0, len(values) - 1)]
    
    return segments


def generate_balance_chart(
    data: List[Dict],
    period: str = "1d",
    currency: str = "RUB"
) -> bytes:
    """
    Генерирует график динамики баланса портфеля.
    
    Args:
        data: Список словарей с полями 'timestamp' (datetime) и 'value' (float)
        period: Период отображения ('1h', '1d', '1w', '1m', '1y')
        currency: Валюта для отображения
        
    Returns:
        bytes: Изображение графика в формате PNG
    """
    if not data:
        logger.warning("Нет данных для построения графика баланса")
        return _generate_empty_chart("Нет данных для отображения")
    
    try:
        # Извлекаем данные
        timestamps = [item['timestamp'] for item in data]
        values = [item['value'] for item in data]
        
        if len(values) < 2:
            return _generate_empty_chart("Недостаточно данных для графика")
        
        # Создаем фигуру и оси
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor('#f5f5f5')
        ax.set_facecolor('#ffffff')
        
        # Строим график
        ax.plot(timestamps, values, linewidth=2.5, color='#3b82f6', label='Баланс портфеля', zorder=2)
        
        # Находим сегменты тренда
        segments = _find_trend_segments(timestamps, values)
        
        # Рисуем линии тренда для каждого сегмента
        for start_idx, end_idx in segments:
            # Пропускаем сегменты с одной точкой или недостаточными данными
            if end_idx <= start_idx:
                continue
            
            segment_times = timestamps[start_idx:end_idx+1]
            segment_values = values[start_idx:end_idx+1]
            
            # Рассчитываем линию тренда (линейная регрессия)
            if len(segment_values) >= 2:
                # Простая линейная аппроксимация
                y1, y2 = segment_values[0], segment_values[-1]
                
                # Определяем цвет тренда
                trend_color = '#10b981' if y2 >= y1 else '#ef4444'
                
                # Рисуем линию тренда
                ax.plot([segment_times[0], segment_times[-1]], 
                       [y1, y2],
                       color=trend_color, 
                       linestyle='--', 
                       linewidth=2,
                       alpha=0.7,
                       zorder=1)
        
        # Рассчитываем прибыль/убыток
        start_value = values[0]
        end_value = values[-1]
        profit_loss = end_value - start_value
        profit_loss_percent = (profit_loss / start_value * 100) if start_value != 0 else 0
        
        # Определяем цвет и эмодзи для легенды
        pl_color = '#10b981' if profit_loss >= 0 else '#ef4444'
        pl_sign = '+' if profit_loss >= 0 else ''
        pl_emoji = '📈' if profit_loss >= 0 else '📉'
        pl_label = f'{pl_emoji} {pl_sign}{format_currency(profit_loss, currency)} ({pl_sign}{profit_loss_percent:.2f}%)'
        
        # Добавляем информацию о прибыли/убытке в легенду
        ax.plot([], [], color=pl_color, linewidth=3, label=pl_label)
        
        # Настройка осей
        ax.set_xlabel('Время', fontsize=12, fontweight='bold')
        ax.set_ylabel('Баланс', fontsize=12, fontweight='bold')
        ax.set_title('Динамика баланса портфеля', fontsize=14, fontweight='bold', pad=20)
        
        # Форматирование оси X в зависимости от периода
        if period == '1h':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        elif period == '1d':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        elif period == '1w':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator())
        elif period == '1m':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator())
        elif period == '1y':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
        
        plt.xticks(rotation=45, ha='right')
        
        # Форматирование оси Y
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: format_currency(y, currency)))
        
        # Сетка
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Легенда
        ax.legend(loc='upper left', framealpha=0.95, fontsize=10)
        
        # Плотная компоновка
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        
        logger.info(f"График баланса успешно сгенерирован для периода {period}")
        return buf.getvalue()
        
    except Exception as e:
        logger.error(f"Ошибка при генерации графика баланса: {e}", exc_info=True)
        return _generate_empty_chart("Ошибка генерации графика")


def generate_stock_chart(
    figi: str,
    data: List[Dict],
    period: str = "1d",
    ticker: str = "STOCK",
    currency: str = "RUB"
) -> bytes:
    """
    Генерирует график динамики цены акции.
    
    Args:
        figi: Идентификатор инструмента
        data: Список словарей с полями 'timestamp' (datetime) и 'price' (float)
        period: Период отображения ('1h', '1d', '1w', '1m', '1y')
        ticker: Тикер акции для заголовка
        currency: Валюта для отображения
        
    Returns:
        bytes: Изображение графика в формате PNG
    """
    if not data:
        logger.warning(f"Нет данных для построения графика акции {figi}")
        return _generate_empty_chart("Нет данных для отображения")
    
    try:
        # Извлекаем данные
        timestamps = [item['timestamp'] for item in data]
        prices = [item['price'] for item in data]
        
        if len(prices) < 2:
            return _generate_empty_chart("Недостаточно данных для графика")
        
        # Создаем фигуру и оси
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor('#f5f5f5')
        ax.set_facecolor('#ffffff')
        
        # Строим график
        ax.plot(timestamps, prices, linewidth=2.5, color='#8b5cf6', label=f'Цена {ticker}', zorder=2)
        
        # Находим сегменты тренда
        segments = _find_trend_segments(timestamps, prices)
        
        # Рисуем линии тренда для каждого сегмента
        for start_idx, end_idx in segments:
            # Пропускаем сегменты с одной точкой или недостаточными данными
            if end_idx <= start_idx:
                continue
            
            segment_times = timestamps[start_idx:end_idx+1]
            segment_prices = prices[start_idx:end_idx+1]
            
            # Рассчитываем линию тренда (линейная регрессия)
            if len(segment_prices) >= 2:
                # Простая линейная аппроксимация
                y1, y2 = segment_prices[0], segment_prices[-1]
                
                # Определяем цвет тренда
                trend_color = '#10b981' if y2 >= y1 else '#ef4444'
                
                # Рисуем линию тренда
                ax.plot([segment_times[0], segment_times[-1]], 
                       [y1, y2],
                       color=trend_color, 
                       linestyle='--', 
                       linewidth=2,
                       alpha=0.7,
                       zorder=1)
        
        # Рассчитываем прибыль/убыток
        start_price = prices[0]
        end_price = prices[-1]
        price_change = end_price - start_price
        price_change_percent = (price_change / start_price * 100) if start_price != 0 else 0
        
        # Определяем цвет и эмодзи для легенды
        pc_color = '#10b981' if price_change >= 0 else '#ef4444'
        pc_sign = '+' if price_change >= 0 else ''
        pc_emoji = '📈' if price_change >= 0 else '📉'
        pc_label = f'{pc_emoji} {pc_sign}{format_currency(price_change, currency)} ({pc_sign}{price_change_percent:.2f}%)'
        
        # Добавляем информацию о прибыли/убытке в легенду
        ax.plot([], [], color=pc_color, linewidth=3, label=pc_label)
        
        # Настройка осей
        ax.set_xlabel('Время', fontsize=12, fontweight='bold')
        ax.set_ylabel('Цена', fontsize=12, fontweight='bold')
        ax.set_title(f'Динамика цены акции {ticker}', fontsize=14, fontweight='bold', pad=20)
        
        # Форматирование оси X в зависимости от периода
        if period == '1h':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=15))
        elif period == '1d':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        elif period == '1w':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator())
        elif period == '1m':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator())
        elif period == '1y':
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
        
        plt.xticks(rotation=45, ha='right')
        
        # Форматирование оси Y
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: format_currency(y, currency)))
        
        # Сетка
        ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
        
        # Легенда
        ax.legend(loc='upper left', framealpha=0.95, fontsize=10)
        
        # Плотная компоновка
        plt.tight_layout()
        
        # Сохранение в буфер
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        
        logger.info(f"График акции {ticker} успешно сгенерирован для периода {period}")
        return buf.getvalue()
        
    except Exception as e:
        logger.error(f"Ошибка при генерации графика акции: {e}", exc_info=True)
        return _generate_empty_chart("Ошибка генерации графика")


def _generate_empty_chart(message: str) -> bytes:
    """
    Генерирует пустой график с сообщением.
    
    Args:
        message: Сообщение для отображения
        
    Returns:
        bytes: Изображение графика в формате PNG
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#f5f5f5')
    ax.set_facecolor('#ffffff')
    
    ax.text(0.5, 0.5, message, ha='center', va='center', 
            fontsize=16, color='#64748b', transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.spines['left'].set_visible(False)
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    
    return buf.getvalue()
