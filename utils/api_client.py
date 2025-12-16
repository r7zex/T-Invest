import requests
import os
import logging
import time
import threading
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

# Правильный URL для prod (обновлённый после ребрендинга)
BASE_URL = "https://invest-public-api.tbank.ru/rest"

TEMP_URL = "https://sandbox-invest-public-api.tbank.ru"

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
        logger.info("🔍 Запрос списка счетов пользователя")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        logger.info(f"📡 Статус ответа API: {response.status_code}")

        response.raise_for_status()
        result = response.json()

        accounts = result.get("accounts", [])

        if not accounts:
            logger.warning("⚠️ У пользователя нет доступных счетов")
            logger.info(f"📄 Полный ответ API: {result}")
            return []

        logger.info(f"✅ Получено {len(accounts)} счетов")
        for idx, acc in enumerate(accounts):
            logger.info(f"  📋 Счёт {idx + 1}: ID={acc.get('id')}, Type={acc.get('type')}")

        return accounts

    except requests.exceptions.HTTPError as err:
        logger.error(f"❌ HTTP ошибка при запросе счетов: {err}")
        logger.error(f"   Статус: {err.response.status_code}")
        try:
            logger.error(f"   Ответ: {err.response.json()}")
        except:
            logger.error(f"   Ответ: {err.response.text}")
        return []
    except requests.exceptions.RequestException as err:
        logger.error(f"❌ Ошибка при запросе списка счетов: {err}")
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
        logger.info(f"🔍 Запрос портфеля для счёта {account_id}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        logger.info(f"📡 Статус ответа API: {response.status_code}")

        response.raise_for_status()
        result = response.json()

        positions = result.get("positions", [])
        virtual_positions = result.get("virtualPositions", [])

        logger.info(f"✅ В портфеле {len(positions)} обычных позиций")
        logger.info(f"🎁 В портфеле {len(virtual_positions)} подарочных позиций")

        # Логируем ключи в ответе для отладки
        logger.info(f"📋 Ключи в ответе портфеля: {list(result.keys())}")

        return result

    except requests.exceptions.HTTPError as err:
        logger.error(f"❌ HTTP ошибка при запросе портфеля: {err}")
        logger.error(f"   Статус: {err.response.status_code}")
        try:
            logger.error(f"   Ответ: {err.response.json()}")
        except:
            logger.error(f"   Ответ: {err.response.text}")
        return None
    except requests.exceptions.RequestException as err:
        logger.error(f"❌ Ошибка при запросе портфеля: {err}")
        return None


def get_portfolio_positions(account_id: str = None, use_cache: bool = True) -> Tuple[List[Dict], Optional[Dict], Optional[str]]:
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
            logger.error("❌ Не удалось получить список счетов")
            return [], None, None
        account_id = accounts[0].get("id")
        logger.info(f"✅ Используется счёт: {account_id}")

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
        logger.error(f"❌ Не удалось получить портфель для счёта {account_id}")
        return [], None, account_id

    logger.info(f"📊 Получен портфель. Ключи в ответе: {list(portfolio.keys())}")

    # Извлекаем только позиции с типом "share" (акции)
    positions = portfolio.get("positions", [])
    virtual_positions = portfolio.get("virtualPositions", [])

    logger.info(f"📦 Обычных позиций: {len(positions)}")
    logger.info(f"🎁 Подарочных позиций: {len(virtual_positions)}")

    # Подсчитываем типы инструментов
    if positions:
        types = {}
        for pos in positions:
            inst_type = pos.get("instrumentType", "unknown")
            types[inst_type] = types.get(inst_type, 0) + 1
        logger.info(f"📋 Типы обычных инструментов: {types}")

    shares = [pos for pos in positions if pos.get("instrumentType") == "share"]
    virtual_shares = []

    for pos in virtual_positions:
        if pos.get("instrumentType") == "share":
            pos_with_flag = pos.copy()
            pos_with_flag["is_virtual"] = True
            virtual_shares.append(pos_with_flag)

    all_shares = shares + virtual_shares

    logger.info(
        f"✅ Найдено {len(all_shares)} акций в портфеле "
        f"(обычных: {len(shares)}, подарочных: {len(virtual_shares)})"
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
        logger.info(f"🔍 Запрос лимитов на вывод для счёта {account_id}")

        response = session.post(
            url,
            json=body,
            timeout=10,
            verify=SSL_VERIFY
        )

        logger.info(f"📡 Статус ответа API: {response.status_code}")

        response.raise_for_status()
        result = response.json()

        if not result:
            logger.warning("⚠️ API вернул пустые лимиты на вывод")
            return None

        logger.info("✅ Успешно получены лимиты на вывод")
        logger.info(f"📋 Ключи в ответе лимитов: {list(result.keys())}")

        # Логируем доступные средства
        money = result.get("money", [])
        blocked = result.get("blocked", [])
        logger.info(f"💰 Доступно валют: {len(money)}")
        logger.info(f"🔒 Заблокировано валют: {len(blocked)}")

        return result

    except requests.exceptions.HTTPError as err:
        logger.error(f"❌ HTTP ошибка при запросе лимитов: {err}")
        logger.error(f"   Статус: {err.response.status_code}")
        try:
            logger.error(f"   Ответ: {err.response.json()}")
        except:
            logger.error(f"   Ответ: {err.response.text}")
        return None
    except requests.exceptions.RequestException as err:
        logger.error(f"❌ Ошибка при запросе лимитов на вывод: {err}")
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