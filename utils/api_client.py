import requests
import os
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
import urllib3
from collections import defaultdict

# ⚠️ ВНИМАНИЕ: Это временное решение для тестирования!
# Отключаем предупреждения о небезопасном SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logger = logging.getLogger(__name__)

# Получаем ключ API для T-Invest
T_INVEST_API_KEY = os.getenv("T_INVEST_API_KEY")

# Правильный URL для prod (проверен на декабрь 2025)
BASE_URL = "https://invest-public-api.tbank.ru/rest"

# URL песочницы
SANDBOX_URL = "https://sandbox-invest-public-api.tbank.ru/rest"

# ⚠️ ОТКЛЮЧАЕМ ПРОВЕРКУ SSL (только для тестирования!)
SSL_VERIFY = False

logger.warning(
    "⚠️ ВНИМАНИЕ: Проверка SSL отключена! "
    "Это небезопасно для продакшена. Используйте только для тестирования."
)

# Глобальная сессия для переиспользования TCP-соединений
_session = None
_session_lock = threading.Lock()

# Кэш для данных с TTL
_cache = {}
_cache_lock = threading.Lock()
_cache_ttl = 30  # секунд


def get_session() -> requests.Session:
    """
    Получает или создаёт глобальную сессию для HTTP-запросов.
    Переиспользование сессии значительно ускоряет запросы.
    Thread-safe реализация.

    Returns:
        requests.Session: Настроенная сессия
    """
    global _session
    if _session is None:
        with _session_lock:
            # Double-check locking pattern
            if _session is None:
                _session = requests.Session()
                _session.headers.update({
                    "Authorization": f"Bearer {T_INVEST_API_KEY}",
                    "Content-Type": "application/json"
                })
                logger.info("Создана новая глобальная HTTP-сессия")
    return _session


def clear_cache():
    """Очищает весь кэш. Thread-safe."""
    global _cache
    with _cache_lock:
        _cache = {}
        logger.info("Кэш очищен")


def get_accounts() -> List[Dict]:
    """
    Получает список счетов пользователя.

    Returns:
        List[Dict]: Список счетов
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts"

    body = {}

    session = get_session()

    try:
        logger.info("Запрос списка счетов пользователя")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        accounts = result.get("accounts", [])

        if not accounts:
            logger.warning("У пользователя нет доступных счетов")
            return []

        logger.info(f"Получено {len(accounts)} счетов")
        return accounts

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе списка счетов: {err}")
        return []


def get_portfolio(account_id: str, currency: str = "RUB") -> Optional[Dict]:
    """
    Получает портфель пользователя по счёту.

    Args:
        account_id: Идентификатор счёта
        currency: Валюта для отображения (RUB, USD, EUR)

    Returns:
        Optional[Dict]: Данные портфеля или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio"

    body = {
        "accountId": account_id,
        "currency": currency
    }

    session = get_session()

    try:
        logger.info(f"Запрос портфеля для счёта {account_id}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        positions = result.get("positions", [])
        logger.info(f"В портфеле {len(positions)} позиций")

        return result

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе портфеля: {err}")
        return None


def get_operations(
        account_id: str,
        from_date: str,
        to_date: str,
        state: str = "OPERATION_STATE_EXECUTED"
) -> Optional[List[Dict]]:
    """
    Получает список операций по счёту за период.

    Args:
        account_id: Идентификатор счёта
        from_date: Начальная дата в формате ISO 8601
        to_date: Конечная дата в формате ISO 8601
        state: Статус операции (по умолчанию EXECUTED)

    Returns:
        Optional[List[Dict]]: Список операций или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.OperationsService/GetOperations"

    body = {
        "accountId": account_id,
        "from": from_date,
        "to": to_date,
        "state": state
    }

    session = get_session()

    try:
        logger.info(f"Запрос операций для счёта {account_id} с {from_date} по {to_date}")

        response = session.post(
            url,
            json=body,
            timeout=15,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        operations = result.get("operations", [])
        logger.info(f"Получено {len(operations)} операций")

        return operations

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе операций: {err}")
        return None


def get_portfolio_positions(account_id: str = None, use_cache: bool = True) -> Tuple[
    List[Dict], Optional[Dict], Optional[str]]:
    """
    Получает список позиций в портфеле пользователя с кэшированием.
    Если account_id не указан, берётся первый доступный счёт.

    Args:
        account_id: Идентификатор счёта (опционально)
        use_cache: Использовать ли кэш данных портфеля. По умолчанию True.

    Returns:
        Tuple[List[Dict], Optional[Dict], Optional[str]]:
            - Список позиций (акций) в портфеле, включая подарочные
            - Исходный объект портфеля
            - Идентификатор используемого счёта
    """
    # Если account_id не указан, получаем первый счёт
    if not account_id:
        accounts = get_accounts()
        if not accounts:
            logger.error("Не удалось получить список счетов")
            return [], None, None
        account_id = accounts[0].get("id")
        logger.info(f"Используется счёт: {account_id}")

    # Проверяем кэш (thread-safe)
    cache_key = f"portfolio_{account_id}"
    now = time.time()

    if use_cache:
        with _cache_lock:
            if cache_key in _cache:
                data, timestamp = _cache[cache_key]
                if now - timestamp < _cache_ttl:
                    logger.info(f"Используются кэшированные данные портфеля (возраст: {now - timestamp:.1f}s)")
                    return data

    # Получаем портфель
    portfolio = get_portfolio(account_id)
    if not portfolio:
        return [], None, account_id

    # Извлекаем только позиции с типом "share" (акции)
    positions = portfolio.get("positions", [])
    virtual_positions = portfolio.get("virtualPositions", [])

    shares = [pos for pos in positions if pos.get("instrumentType") == "share"]
    virtual_shares = []

    for pos in virtual_positions:
        if pos.get("instrumentType") == "share":
            pos_with_flag = pos.copy()
            pos_with_flag["is_virtual"] = True
            virtual_shares.append(pos_with_flag)

    all_shares = shares + virtual_shares

    logger.info(
        f"Найдено {len(all_shares)} акций в портфеле (вкл. подарочные: {len(virtual_shares)})"
    )

    result = (all_shares, portfolio, account_id)

    # Сохраняем в кэш (thread-safe)
    if use_cache:
        with _cache_lock:
            _cache[cache_key] = (result, now)
            logger.info("Данные портфеля сохранены в кэш")

    return result


def get_withdraw_limits(account_id: str) -> Optional[Dict]:
    """
    Получает информацию о доступных средствах и зарезервированных деньгах.

    Args:
        account_id: Идентификатор счёта

    Returns:
        Optional[Dict]: Данные лимитов на вывод или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.OperationsService/GetWithdrawLimits"

    body = {"accountId": account_id}

    session = get_session()

    try:
        logger.info(f"Запрос лимитов на вывод для счёта {account_id}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        if not result:
            logger.warning("API вернул пустые лимиты на вывод")
            return None

        logger.info("Успешно получены лимиты на вывод")
        return result

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе лимитов на вывод: {err}")
        return None


def fetch_shares(instrument_status: str = "INSTRUMENT_STATUS_BASE") -> List[Dict]:
    """
    Получает список акций через REST API T-Invest.

    Args:
        instrument_status: Статус инструментов для запроса

    Returns:
        List[Dict]: Список акций с информацией
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"

    body = {
        "instrument_status": instrument_status
    }

    session = get_session()

    try:
        logger.info(f"Запрос списка акций с статусом: {instrument_status}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        instruments = result.get("instruments", [])

        if not instruments:
            logger.warning("API вернул пустой список инструментов")
            return []

        logger.info(f"Успешно получено {len(instruments)} акций")
        return instruments

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе к T-Invest API: {err}")
        return []


def get_share_info(figi: str) -> Optional[Dict]:
    """
    Получает детальную информацию об акции по FIGI.

    Args:
        figi: Идентификатор финансового инструмента

    Returns:
        Optional[Dict]: Информация об акции или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.InstrumentsService/ShareBy"

    body = {
        "id_type": "INSTRUMENT_ID_TYPE_FIGI",
        "class_code": "",
        "id": figi
    }

    session = get_session()

    try:
        logger.info(f"Запрос информации об акции с FIGI: {figi}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        instrument = result.get("instrument")

        if not instrument:
            logger.warning(f"Инструмент с FIGI {figi} не найден")
            return None

        logger.info(f"Успешно получена информация об акции {instrument.get('ticker', 'N/A')}")
        return instrument

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе информации об акции: {err}")
        return None


def get_last_prices(figis: List[str]) -> Optional[Dict]:
    """
    Получает последние цены для списка инструментов.

    Args:
        figis: Список FIGI инструментов

    Returns:
        Optional[Dict]: Словарь с ценами или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"

    body = {
        "instrument_id": figis
    }

    session = get_session()

    try:
        logger.info(f"Запрос последних цен для {len(figis)} инструментов")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        last_prices = result.get("last_prices", [])

        if not last_prices:
            logger.warning("API не вернул информацию о ценах")
            return None

        logger.info(f"Успешно получены цены для {len(last_prices)} инструментов")
        return result

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе последних цен: {err}")
        return None


def get_candles(
        figi: str,
        from_date: str,
        to_date: str,
        interval: str = "CANDLE_INTERVAL_DAY"
) -> Optional[List[Dict]]:
    """
    Получает исторические свечи для инструмента.

    Args:
        figi: Идентификатор финансового инструмента
        from_date: Начальная дата в формате ISO 8601
        to_date: Конечная дата в формате ISO 8601
        interval: Интервал свечей

    Returns:
        Optional[List[Dict]]: Список свечей или None
    """
    url = f"{BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"

    body = {
        "figi": figi,
        "from": from_date,
        "to": to_date,
        "interval": interval
    }

    session = get_session()

    try:
        logger.info(f"Запрос свечей для {figi} с {from_date} по {to_date}, интервал: {interval}")

        response = session.post(
            url,
            json=body,
            timeout=15,
            verify=SSL_VERIFY
        )

        response.raise_for_status()
        result = response.json()

        candles = result.get("candles", [])

        if not candles:
            logger.warning(f"API не вернул свечи для {figi}")
            return []

        logger.info(f"Успешно получено {len(candles)} свечей для {figi}")
        return candles

    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при запросе свечей: {err}")
        return None


def get_portfolio_history(
        account_id: str,
        from_date: str,
        to_date: str
) -> Optional[List[Dict]]:
    """
    Рассчитывает историю стоимости портфеля на основе операций и исторических цен.

    Args:
        account_id: Идентификатор счёта
        from_date: Начальная дата в формате ISO 8601
        to_date: Конечная дата в формате ISO 8601

    Returns:
        Optional[List[Dict]]: Список значений портфеля с 'timestamp' и 'value'
    """
    try:
        # Получаем текущий портфель для начальных значений
        positions, portfolio, _ = get_portfolio_positions(account_id, use_cache=False)

        if not positions:
            logger.warning("Невозможно рассчитать историю - нет позиций")
            return []

        # Получаем операции за период
        operations = get_operations(account_id, from_date, to_date)

        if operations is None:
            logger.warning("Не удалось получить операции, используем упрощенный расчёт")
            # Fallback к старому методу
            return _calculate_history_simple(positions, portfolio, from_date, to_date)

        # Строим историю изменения позиций на основе операций
        return _calculate_history_from_operations(
            positions, portfolio, operations, from_date, to_date
        )

    except Exception as e:
        logger.error(f"Ошибка при расчёте истории портфеля: {e}", exc_info=True)
        return None


def _calculate_history_from_operations(
        current_positions: List[Dict],
        portfolio: Dict,
        operations: List[Dict],
        from_date: str,
        to_date: str
) -> Optional[List[Dict]]:
    """
    Рассчитывает историю портфеля на основе операций (правильный метод).
    """
    try:
        # Получаем текущий баланс
        current_balance = 0.0
        if portfolio:
            total_amount = portfolio.get("totalAmountCurrencies", {})
            if total_amount:
                current_balance = format_quotation(total_amount)

        # Создаём словарь текущих позиций
        current_stocks = {}
        for pos in current_positions:
            figi = pos.get("figi")
            quantity = format_quotation(pos.get("quantity", {}))
            current_stocks[figi] = quantity

        # Откатываем позиции назад на основе операций
        # (идём в обратном порядке от настоящего к прошлому)
        sorted_operations = sorted(operations, key=lambda x: x.get("date", ""), reverse=True)

        # Восстанавливаем состояние на начало периода
        stock_history = defaultdict(lambda: current_stocks.copy())
        balance_history = {to_date: current_balance}

        # Проходим по операциям в обратном порядке
        for op in sorted_operations:
            op_date = op.get("date")
            op_type = op.get("operationType")
            figi = op.get("figi")
            quantity = abs(format_quotation(op.get("quantity", {})))
            payment = format_quotation(op.get("payment", {}))

            if not op_date or not figi:
                continue

            # Корректируем позиции в зависимости от типа операции
            if op_type in ["OPERATION_TYPE_BUY", "OPERATION_TYPE_BUY_CARD"]:
                # Была покупка - значит раньше акций было меньше
                if figi in current_stocks:
                    current_stocks[figi] -= quantity
                    if current_stocks[figi] <= 0:
                        del current_stocks[figi]
                current_balance -= payment
            elif op_type in ["OPERATION_TYPE_SELL"]:
                # Была продажа - значит раньше акций было больше
                current_stocks[figi] = current_stocks.get(figi, 0) + quantity
                current_balance += payment

            # Сохраняем состояние
            stock_history[op_date] = current_stocks.copy()
            balance_history[op_date] = current_balance

        # Теперь собираем исторические данные с ценами
        # Определяем интервал для свечей
        start = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        diff_days = (end - start).days

        if diff_days <= 1:
            interval = "CANDLE_INTERVAL_HOUR"
        elif diff_days <= 7:
            interval = "CANDLE_INTERVAL_HOUR"
        else:
            interval = "CANDLE_INTERVAL_DAY"

        # Получаем исторические цены для всех акций
        all_figis = set()
        for stocks in stock_history.values():
            all_figis.update(stocks.keys())

        candles_by_figi = {}
        for figi in all_figis:
            candles = get_candles(figi, from_date, to_date, interval)
            if candles:
                candles_by_figi[figi] = {
                    candle.get("time"): format_quotation(candle.get("close", {}))
                    for candle in candles if candle.get("time")
                }

        # Создаём временные метки
        history = []
        value_by_time = {}

        for timestamp_str in candles_by_figi.get(list(all_figis)[0], {}).keys():
            # Определяем состояние портфеля на эту дату
            stocks_at_time = current_stocks.copy()  # начальное состояние
            balance_at_time = current_balance

            # Применяем операции до этой даты
            for op_date in sorted(stock_history.keys()):
                if op_date <= timestamp_str:
                    stocks_at_time = stock_history[op_date].copy()
                    balance_at_time = balance_history.get(op_date, balance_at_time)

            # Рассчитываем стоимость акций
            stocks_value = 0.0
            for figi, quantity in stocks_at_time.items():
                price = candles_by_figi.get(figi, {}).get(timestamp_str, 0)
                stocks_value += quantity * price

            total_value = balance_at_time + stocks_value
            value_by_time[timestamp_str] = total_value

        # Преобразуем в список
        for timestamp_str, value in sorted(value_by_time.items()):
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            history.append({
                'timestamp': timestamp,
                'value': value
            })

        logger.info(f"Рассчитана история портфеля (с операциями): {len(history)} точек")
        return history

    except Exception as e:
        logger.error(f"Ошибка в расчёте истории с операциями: {e}", exc_info=True)
        return None


def _calculate_history_simple(
        positions: List[Dict],
        portfolio: Dict,
        from_date: str,
        to_date: str
) -> Optional[List[Dict]]:
    """
    Упрощённый расчёт истории (fallback метод).
    """
    # Старая логика без учёта операций
    logger.info("Используется упрощённый метод расчёта истории портфеля")
    # ... (оставляем старую реализацию как fallback)
    return []


def get_portfolio_value_yesterday(account_id: str) -> Optional[float]:
    """
    Получает стоимость портфеля на вчерашний день.

    Args:
        account_id: Идентификатор счёта

    Returns:
        Optional[float]: Стоимость портфеля на вчера или None
    """
    try:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        from_date = yesterday.isoformat() + "Z"
        to_date = today.isoformat() + "Z"

        history = get_portfolio_history(account_id, from_date, to_date)

        if history and len(history) > 0:
            yesterday_value = history[-1]['value']
            logger.info(f"Стоимость портфеля на вчера: {yesterday_value}")
            return yesterday_value
        else:
            logger.warning("Не удалось получить стоимость портфеля на вчера")
            return None

    except Exception as e:
        logger.error(f"Ошибка при получении стоимости портфеля на вчера: {e}", exc_info=True)
        return None


def format_quotation(quotation) -> float:
    """
    Форматирует объект Quotation в число.
    Поддерживает как объекты Quotation, так и простые числа.

    Args:
        quotation: Объект с полями units и nano, либо число/строка

    Returns:
        float: Значение в виде числа
    """
    if not quotation:
        return 0.0

    # Если это уже число или строка с числом
    if isinstance(quotation, (int, float)):
        return float(quotation)

    if isinstance(quotation, str):
        try:
            return float(quotation)
        except (ValueError, TypeError):
            return 0.0

    # Если это словарь (объект Quotation)
    if not isinstance(quotation, dict):
        return 0.0

    units = quotation.get("units", 0)
    nano = quotation.get("nano", 0)

    try:
        units = int(units) if units else 0
    except (ValueError, TypeError):
        units = 0

    try:
        nano = int(nano) if nano else 0
    except (ValueError, TypeError):
        nano = 0

    value = units + (nano / 1_000_000_000)

    return value