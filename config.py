"""
Конфиг для crypto-scalper-bot
Читает переменные окружения вместо хардкода
"""
import os

# Telegram
TELEGRAM_TOKEN   = os.environ.get("SCALPER_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("SCALPER_CHAT_ID", "")

# Binance
BINANCE_BASE_URL = "https://fapi.binance.com"

# Торговые параметры
SCAN_INTERVAL    = 900   # 15 минут
SIGNAL_COOLDOWN  = 3600  # 1 час между сигналами для одной пары
MIN_BUY_COUNT    = 12    # минимум BUY сигналов TradingView
MIN_SELL_COUNT   = 12    # минимум SELL сигналов

# Время торговли (по Киеву)
TRADING_HOUR_START = 10
TRADING_HOUR_END   = 22
TIMEZONE_OFFSET    = 2   # UTC+2 (Киев зима) или 3 летом

# Фильтры
VOLUME_SPIKE_MIN  = 1.3  # объём в 1.3x выше среднего
LEVEL_BUFFER_PCT  = 1.0  # 1% буфер от уровня
BTC_DROP_BLOCK_PCT = -3.0  # блок LONG если BTC упал на 3%+
BTC_PUMP_BLOCK_PCT = 3.0   # блок SHORT если BTC вырос на 3%+

# Торговые пары
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
    "FTMUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT", "GALAUSDT",
]
