import requests
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Получаем ключ API для Tinkoff Invest
T_INVEST_API_KEY = os.getenv("T_INVEST_API_KEY")


def fetch_shares():
    """
    Получает список акций через REST‑прокси T‑Invest API —
    метод InstrumentsService/Shares.
    """
    url = "https://invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    headers = {
        "Authorization": f"Bearer {T_INVEST_API_KEY}",
        "Content-Type": "application/json"
    }
    body = {}

    try:
        # Выполняем POST-запрос на получение списка акций
        response = requests.post(url, json=body, headers=headers, timeout=10, verify=True)
        response.raise_for_status()  # Проверяем на ошибки HTTP
        result = response.json()

        # Возвращаем список акций, если он есть
        return result.get("instruments", [])

    except requests.exceptions.SSLError as ssl_err:
        print(
            "Ошибка SSL. Убедитесь, что у вас свежие корневые сертификаты и что вы не отключаете verify=True. Подробнее: ",
            ssl_err)
        return []
    except requests.exceptions.RequestException as err:
        print(f"[T‑Invest API] Ошибка при запросе списка акций: {err}")
        return []
