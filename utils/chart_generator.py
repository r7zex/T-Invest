"""
Модуль для генерации графиков динамики баланса и стоимости акций.
"""
import matplotlib
matplotlib.use('Agg')  # Использование non-GUI backend для серверных приложений

import io
import logging
from datetime import datetime
from typing import List, Dict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
import numpy as np

logger = logging.getLogger(__name__)

# Настройка шрифта для избежания предупреждений
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']


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


def get_price_precision(price: float) -> int:
    """
    Определяет количество знаков после запятой для цены.

    Args:
        price: Цена

    Returns:
        int: Количество знаков после запятой
    """
    if price < 1:
        # Для цен < 1 рубля - до первых трёх ненулевых цифр после запятой
        price_str = f"{price:.10f}"
        after_dot = price_str.split('.')[1] if '.' in price_str else ""
        non_zero_count = 0
        for char in after_dot:
            if char != '0':
                non_zero_count += 1
            if non_zero_count >= 3:
                return len(after_dot[:after_dot.index(char) + 1])
        return 10  # Максимум 10 знаков
    elif price >= 1 and price < 10:
        return 3
    elif price >= 10 and price < 1000:
        return 2
    else:  # >= 1000
        return 1


def format_price_with_precision(value: float, currency: str = "RUB") -> str:
    """
    Форматирует цену с правильной точностью.

    Args:
        value: Значение цены
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
    precision = get_price_precision(abs(value))

    # Форматируем с нужной точностью
    formatted = f"{value:.{precision}f}"

    return f"{formatted}{symbol}"


def calculate_linear_trend(x_values: np.ndarray, y_values: np.ndarray) -> tuple:
    """
    Рассчитывает линейный тренд методом наименьших квадратов.

    Args:
        x_values: Массив значений X (временные метки как числа)
        y_values: Массив значений Y (цены/балансы)

    Returns:
        tuple: (коэффициент наклона, свободный член)
    """
    if len(x_values) < 2:
        return 0, np.mean(y_values) if len(y_values) > 0 else 0

    # Линейная регрессия методом наименьших квадратов
    # y = a*x + b
    n = len(x_values)
    sum_x = np.sum(x_values)
    sum_y = np.sum(y_values)
    sum_xy = np.sum(x_values * y_values)
    sum_x2 = np.sum(x_values ** 2)

    # Избегаем деления на ноль
    denominator = n * sum_x2 - sum_x ** 2
    if abs(denominator) < 1e-10:
        return 0, np.mean(y_values)

    a = (n * sum_xy - sum_x * sum_y) / denominator
    b = (sum_y - a * sum_x) / n

    return a, b


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

        # Создаем фигуру и оси с увеличенным размером для названий
        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#f5f5f5')
        ax.set_facecolor('#ffffff')

        # Строим график значений
        ax.plot(timestamps, values, linewidth=2.5, color='#3b82f6', label='Баланс портфеля', zorder=3)

        # Рассчитываем линию тренда
        # Преобразуем timestamps в числа для расчёта
        x_numeric = np.array([t.timestamp() for t in timestamps])
        y_values = np.array(values)

        a, b = calculate_linear_trend(x_numeric, y_values)

        # Рассчитываем значения линии тренда
        trend_values = a * x_numeric + b

        # Определяем цвет тренда
        trend_color = '#10b981' if a >= 0 else '#ef4444'

        # Рисуем линию тренда
        ax.plot(timestamps, trend_values,
               color=trend_color,
               linestyle='--',
               linewidth=2,
               alpha=0.7,
               label='Линия тренда',
               zorder=2)

        # Рассчитываем изменение между ПЕРВЫМ и ПОСЛЕДНИМ значением
        start_value = values[0]
        end_value = values[-1]
        profit_loss = end_value - start_value
        profit_loss_percent = (profit_loss / start_value * 100) if start_value != 0 else 0

        # Определяем цвет и символ для легенды (используем текст вместо эмодзи)
        pl_color = '#10b981' if profit_loss >= 0 else '#ef4444'
        pl_sign = '+' if profit_loss >= 0 else ''

        # Форматируем изменение с правильной точностью
        pl_label = f'Изменение: {pl_sign}{format_price_with_precision(profit_loss, currency)} ({pl_sign}{profit_loss_percent:.2f}%)'

        # Добавляем информацию о прибыли/убытке в легенду
        ax.plot([], [], color=pl_color, linewidth=3, label=pl_label)

        # Настройка осей
        ax.set_xlabel('Время', fontsize=12, fontweight='bold')
        ax.set_ylabel('Баланс', fontsize=12, fontweight='bold')
        ax.set_title('Динамика баланса портфеля', fontsize=14, fontweight='bold', pad=20)

        # ИСПРАВЛЕНИЕ: Устанавливаем ylim с отступами сверху и снизу
        max_value = max(values)
        min_value = min(values)
        value_range = max_value - min_value

        ax.set_ylim(bottom=min_value - value_range * 0.2, top=max_value + value_range * 0.2)

        # Форматирование оси X в зависимости от периода (упрощённые интервалы)
        if period == '1h':
            # 1 час - каждые 10 минут
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        elif period == '1d':
            # 1 день - каждые 4 часа
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
        elif period == '1w':
            # 1 неделя - каждый день
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        elif period == '1m':
            # 1 месяц - каждые 3 дня
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        elif period == '1y':
            # 1 год - каждые 2 недели (примерно 14 дней)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))

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
    stock_name: str = "STOCK",
    currency: str = "RUB"
) -> bytes:
    """
    Генерирует график динамики цены акции.

    Args:
        figi: Идентификатор инструмента
        data: Список словарей с полями 'timestamp' (datetime) и 'price' (float)
        period: Период отображения ('1h', '1d', '1w', '1m', '1y')
        stock_name: Название акции для заголовка (не тикер!)
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

        # Создаем фигуру и оси с увеличенным размером для названий
        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#f5f5f5')
        ax.set_facecolor('#ffffff')

        # Строим график цен
        ax.plot(timestamps, prices, linewidth=2.5, color='#8b5cf6', label=f'Цена {stock_name}', zorder=3)

        # Рассчитываем линию тренда
        # Преобразуем timestamps в числа для расчёта
        x_numeric = np.array([t.timestamp() for t in timestamps])
        y_values = np.array(prices)

        a, b = calculate_linear_trend(x_numeric, y_values)

        # Рассчитываем значения линии тренда
        trend_values = a * x_numeric + b

        # Определяем цвет тренда
        trend_color = '#10b981' if a >= 0 else '#ef4444'

        # Рисуем линию тренда
        ax.plot(timestamps, trend_values,
               color=trend_color,
               linestyle='--',
               linewidth=2,
               alpha=0.7,
               label='Линия тренда',
               zorder=2)

        # Рассчитываем изменение между ПЕРВЫМ и ПОСЛЕДНИМ значением
        start_price = prices[0]
        end_price = prices[-1]
        price_change = end_price - start_price
        price_change_percent = (price_change / start_price * 100) if start_price != 0 else 0

        # Определяем цвет и символ для легенды (используем текст вместо эмодзи)
        pc_color = '#10b981' if price_change >= 0 else '#ef4444'
        pc_sign = '+' if price_change >= 0 else ''

        # Форматируем изменение с правильной точностью
        pc_label = f'Изменение: {pc_sign}{format_price_with_precision(price_change, currency)} ({pc_sign}{price_change_percent:.2f}%)'

        # Добавляем информацию о прибыли/убытке в легенду
        ax.plot([], [], color=pc_color, linewidth=3, label=pc_label)

        # Настройка осей
        ax.set_xlabel('Время', fontsize=12, fontweight='bold')
        ax.set_ylabel('Цена', fontsize=12, fontweight='bold')
        ax.set_title(f'Динамика цены акции {stock_name}', fontsize=14, fontweight='bold', pad=20)

        # ИСПРАВЛЕНИЕ: Устанавливаем ylim с отступами сверху и снизу
        max_price = max(prices)
        min_price = min(prices)
        price_range = max_price - min_price

        ax.set_ylim(bottom=min_price - price_range * 0.2, top=max_price + price_range * 0.2)

        # Форматирование оси X в зависимости от периода (упрощённые интервалы)
        if period == '1h':
            # 1 час - каждые 10 минут
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
        elif period == '1d':
            # 1 день - каждые 4 часа
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
        elif period == '1w':
            # 1 неделя - каждый день
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        elif period == '1m':
            # 1 месяц - каждые 3 дня
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
        elif period == '1y':
            # 1 год - каждые 2 недели (примерно 14 дней)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))

        plt.xticks(rotation=45, ha='right')

        # Форматирование оси Y с правильной точностью
        def format_y_axis(y, _):
            return format_price_with_precision(y, currency)

        ax.yaxis.set_major_formatter(FuncFormatter(format_y_axis))

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

        logger.info(f"График акции {stock_name} успешно сгенерирован для периода {period}")
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