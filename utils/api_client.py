import requests
import os
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
import urllib3

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


def get_portfolio_positions(account_id: str = None, use_cache: bool = True) -> Tuple[
    List[Dict], Optional[Dict], Optional[str]]:
    """
    Получает список позиций в портфеле пользователя с кэшированием.
    Если account_id не указан, берётся первый доступный счёт.

    Args:
        account_id: Идентификатор счёта (опционально)
        use_cache: Использовать ли кэш данных портфеля. По умолчанию True.
            При True данные кэшируются на _cache_ttl секунд (30 сек).
            При False всегда делается свежий запрос к API.

    Returns:
        Tuple[List[Dict], Optional[Dict], Optional[str]]:
            - Список позиций (акций) в портфеле, включая подарочные
            - Исходный объект портфеля
            - Идентификатор используемого счёта

    Note:
        Кэшированные данные используются для уменьшения нагрузки на API
        и ускорения повторных запросов в течение TTL.
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
            - INSTRUMENT_STATUS_BASE: базовый список (по умолчанию)
            - INSTRUMENT_STATUS_ALL: все инструменты

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
        Optional[Dict]: Информация об акции или None в случае ошибки
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
        from_date: Начальная дата в формате ISO 8601 (например, '2024-01-01T00:00:00Z')
        to_date: Конечная дата в формате ISO 8601
        interval: Интервал свечей:
            - CANDLE_INTERVAL_1_MIN: 1 минута
            - CANDLE_INTERVAL_5_MIN: 5 минут
            - CANDLE_INTERVAL_15_MIN: 15 минут
            - CANDLE_INTERVAL_HOUR: 1 час
            - CANDLE_INTERVAL_DAY: 1 день (по умолчанию)
            - CANDLE_INTERVAL_WEEK: 1 неделя
            - CANDLE_INTERVAL_MONTH: 1 месяц

    Returns:
        Optional[List[Dict]]: Список свечей или None в случае ошибки
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
    Рассчитывает историю стоимости портфеля на основе исторических данных акций.

    Поскольку T-Invest API не предоставляет прямой метод для получения истории портфеля,
    эта функция рассчитывает стоимость на основе текущих позиций и исторических цен.

    Args:
        account_id: Идентификатор счёта
        from_date: Начальная дата в формате ISO 8601
        to_date: Конечная дата в формате ISO 8601

    Returns:
        Optional[List[Dict]]: Список значений портфеля с полями 'timestamp' и 'value'
    """
    try:
        # Получаем текущие позиции портфеля
        positions, portfolio, _ = get_portfolio_positions(account_id, use_cache=False)

        if not positions:
            logger.warning("Невозможно рассчитать историю портфеля - нет позиций")
            return []

        # Получаем текущий баланс
        current_balance = 0.0
        if portfolio:
            total_amount = portfolio.get("totalAmountCurrencies", {})
            if total_amount:
                current_balance = format_quotation(total_amount)

        # Определяем интервал на основе разницы дат
        start = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        end = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
        diff_days = (end - start).days

        if diff_days <= 1:
            interval = "CANDLE_INTERVAL_HOUR"
        elif diff_days <= 7:
            interval = "CANDLE_INTERVAL_HOUR"
        elif diff_days <= 30:
            interval = "CANDLE_INTERVAL_DAY"
        else:
            interval = "CANDLE_INTERVAL_DAY"

        # Словарь для хранения исторических данных по каждой позиции
        position_histories = {}

        for position in positions:
            figi = position.get("figi")
            quantity = format_quotation(position.get("quantity", {}))

            if not figi or quantity == 0:
                continue

            # Получаем исторические свечи для акции
            candles = get_candles(figi, from_date, to_date, interval)

            if candles:
                position_histories[figi] = {
                    'quantity': quantity,
                    'candles': candles
                }

        if not position_histories:
            logger.warning("Не удалось получить исторические данные для позиций")
            return []

        # Создаем словарь timestamp -> total_value
        value_by_time = {}

        # Для каждой временной точки рассчитываем общую стоимость портфеля
        for figi, hist_data in position_histories.items():
            quantity = hist_data['quantity']
            candles = hist_data['candles']

            for candle in candles:
                timestamp = candle.get('time')
                if not timestamp:
                    continue

                # Используем цену закрытия свечи
                close_price = format_quotation(candle.get('close', {}))

                if timestamp not in value_by_time:
                    value_by_time[timestamp] = current_balance

                value_by_time[timestamp] += quantity * close_price

        # Преобразуем в список отсортированных значений
        history = []
        for timestamp_str, value in sorted(value_by_time.items()):
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                history.append({
                    'timestamp': timestamp,
                    'value': value
                })
            except Exception as e:
                logger.warning(f"Не удалось преобразовать timestamp {timestamp_str}: {e}")
                continue

        logger.info(f"Рассчитана история портфеля: {len(history)} точек")
        return history

    except Exception as e:
        logger.error(f"Ошибка при расчёте истории портфеля: {e}", exc_info=True)
        return None


def get_portfolio_value_yesterday(account_id: str) -> Optional[float]:
    """
    Получает стоимость портфеля на вчерашний день (для расчёта изменения за сегодня).

    Args:
        account_id: Идентификатор счёта

    Returns:
        Optional[float]: Стоимость портфеля на вчерашний день или None
    """
    try:
        # Определяем временной диапазон (вчера)
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        from_date = yesterday.isoformat() + "Z"
        to_date = today.isoformat() + "Z"

        # Получаем историю портфеля
        history = get_portfolio_history(account_id, from_date, to_date)

        if history and len(history) > 0:
            # Берём последнее значение (самое близкое к концу вчерашнего дня)
            yesterday_value = history[-1]['value']
            logger.info(f"Стоимость портфеля на вчера: {yesterday_value}")
            return yesterday_value
        else:
            logger.warning("Не удалось получить стоимость портфеля на вчера")
            return None

    except Exception as e:
        logger.error(f"Ошибка при получении стоимости портфеля на вчера: {e}", exc_info=True)
        return None


def format_quotation(quotation: Dict) -> float:
    """
    Форматирует объект Quotation в число.

    Args:
        quotation: Объект с полями units и nano

    Returns:
        float: Значение в виде числа
    """
    if not quotation:
        return 0.0

    # Получаем units и nano
    units = quotation.get("units", 0)
    nano = quotation.get("nano", 0)

    # Преобразуем в числа, если пришли строки
    try:
        units = int(units) if units else 0
    except (ValueError, TypeError):
        units = 0

    try:
        nano = int(nano) if nano else 0
    except (ValueError, TypeError):
        nano = 0

    # Преобразуем nano (дробная часть в единицах 10^-9) в дробную часть
    value = units + (nano / 1_000_000_000)

    return value