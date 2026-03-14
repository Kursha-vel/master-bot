# -*- coding: utf-8 -*-
"""
FOOTBALL ANALYZER BOT V7.6
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Основано на анализе матчей тестирования V7.5 (11-13.03.2026)

Статистика V7.5:
   • Нацчемпионаты: Исход 43% ❌ | Тотал 75% ✅
   • ЛЧ: Исход 50% | Тотал 100%
   • Главная проблема: standings=None → gap=0 → бред!

ИЗМЕНЕНИЯ V7.6 (vs V7.5):
━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ #1 FALLBACK КЛАССИФИКАЦИЯ (ПРИОРИТЕТ #1!)
   - Раньше: standings=None → home_pos=10, away_pos=10 → gap=0 → "Близкие команды"
   - Marseille(3) vs Auxerre(16) = gap 13 → бот давал X. ПОЗОР!
   - Теперь: если нет таблицы → классифицируем по КОЭФФИЦИЕНТАМ + ML
   - П1 @ 1.42 = ~70% за хозяев → CLEAR_FAVORITE автоматически

✅ #2 ЗОНА ВЫЛЕТА ГОСТЕЙ ПЕРЕБИВАЕТ CLOSE
   - Gladbach(12) vs St.Pauli(16): gap=4 → CLOSE → X рекомендован
   - Реально: St.Pauli в зоне вылета → Gladbach дома П1 2:0
   - Теперь: если гости в зоне вылета + хозяева топ → рекомендовать П1

✅ #3 ЛЧ ПОРОГ ТБ: 68% → 65%
   - Real Madrid-Man City: ТБ 67.9% — не рекомендовал (3 гола!)
   - На 0.1% не хватило → снижаем порог

Статистика ожидаемая V7.6:
   • Нацчемпионаты: Исход 60%+ | Тотал 75%+
"""

import logging
import requests
import time
import os
import json
import re
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ КОНФИГУРАЦИЯ ============
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
FOOTBALLDATA_API_KEY = os.environ.get('FOOTBALLDATA_API_KEY', '')
ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '')

FOOTBALLDATA_BASE_URL = "https://api.football-data.org/v4"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"

LEAGUES = {
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Champions League": "CL",
    "Eredivisie": "DED",
    "Primeira Liga": "PPL",
}

ODDS_LEAGUES = {
    'PL': 'soccer_epl',
    'PD': 'soccer_spain_la_liga',
    'SA': 'soccer_italy_serie_a',
    'BL1': 'soccer_germany_bundesliga',
    'FL1': 'soccer_france_ligue_one',
    'CL': 'soccer_uefa_champs_league',
    'DED': 'soccer_netherlands_eredivisie',
    'PPL': 'soccer_portugal_primeira_liga',
}

UNDERSTAT_LEAGUES = {
    'PL': 'EPL',
    'PD': 'La_liga',
    'SA': 'Serie_A',
    'BL1': 'Bundesliga',
    'FL1': 'Ligue_1',
}

REQUEST_DELAY = 1

# ============================================================
# СИСТЕМА АВТОРИЗАЦИИ
# ============================================================
# Твой Telegram user_id — получи его написав @userinfobot
# Только ты видишь запросы и одобряешь пользователей
ADMIN_ID = int(os.environ.get('ADMIN_TELEGRAM_ID', '0'))

# Файл хранения авторизованных пользователей
AUTH_FILE = 'authorized_users.json'

def load_authorized():
    """Загрузить список авторизованных пользователей"""
    try:
        if os.path.exists(AUTH_FILE):
            with open(AUTH_FILE, 'r') as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_authorized(users: set):
    """Сохранить список авторизованных пользователей"""
    with open(AUTH_FILE, 'w') as f:
        json.dump(list(users), f)

# Загружаем при старте
AUTHORIZED_USERS = load_authorized()

def is_authorized(user_id: int) -> bool:
    """Проверить авторизован ли пользователь"""
    return user_id == ADMIN_ID or user_id in AUTHORIZED_USERS

def authorize_user(user_id: int):
    """Добавить пользователя в список авторизованных"""
    AUTHORIZED_USERS.add(user_id)
    save_authorized(AUTHORIZED_USERS)

def revoke_user(user_id: int):
    """Убрать пользователя из авторизованных"""
    AUTHORIZED_USERS.discard(user_id)
    save_authorized(AUTHORIZED_USERS)


# ============================================================
# V7.4: ДЕТЕКТОР ДЕРБИ (ПО ГОРОДУ — исправлен баг V7.3!)
# ============================================================
# Словарь: нормализованное имя → город
# Дерби = обе команды из одного города
TEAM_CITY = {
    # Premier League
    'manchester city': 'manchester',
    'manchester united': 'manchester',
    'arsenal': 'london',
    'chelsea': 'london',
    'tottenham': 'london',
    'tottenham hotspur': 'london',
    'west ham': 'london',
    'west ham united': 'london',
    'crystal palace': 'london',
    'fulham': 'london',
    'brentford': 'london',
    'charlton': 'london',
    'millwall': 'london',
    'liverpool': 'liverpool',
    'everton': 'liverpool',
    'newcastle': 'newcastle',
    'newcastle united': 'newcastle',
    'sunderland': 'sunderland',
    'leeds': 'leeds',
    'leeds united': 'leeds',
    'aston villa': 'birmingham',
    'birmingham': 'birmingham',
    'birmingham city': 'birmingham',
    'wolves': 'wolverhampton',
    'wolverhampton': 'wolverhampton',
    'west brom': 'birmingham',
    'west bromwich': 'birmingham',
    'brighton': 'brighton',
    'sheffield united': 'sheffield',
    'sheffield wednesday': 'sheffield',
    'nottingham forest': 'nottingham',
    'notts county': 'nottingham',
    'burnley': 'burnley',
    'blackburn': 'blackburn',

    # La Liga
    'real madrid': 'madrid',
    'atletico madrid': 'madrid',
    'atletico de madrid': 'madrid',
    'getafe': 'madrid',
    'rayo vallecano': 'madrid',
    'rayo vallecano de madrid': 'madrid',
    'leganes': 'madrid',
    'fc barcelona': 'barcelona',
    'barcelona': 'barcelona',
    'espanyol': 'barcelona',
    'real betis': 'sevilla',
    'real betis balompie': 'sevilla',
    'sevilla': 'sevilla',
    'sevilla fc': 'sevilla',
    'athletic': 'bilbao',
    'athletic club': 'bilbao',
    'real sociedad': 'san_sebastian',
    'valencia': 'valencia',
    'villarreal': 'villarreal',
    'real oviedo': 'oviedo',
    'sporting de gijon': 'gijon',

    # Serie A
    'inter': 'milan',
    'internazionale': 'milan',
    'ac milan': 'milan',
    'milan': 'milan',
    'roma': 'rome',
    'lazio': 'rome',
    'juventus': 'turin',
    'torino': 'turin',
    'napoli': 'naples',
    'fiorentina': 'florence',
    'genoa': 'genoa',
    'sampdoria': 'genoa',
    'atalanta': 'bergamo',

    # Bundesliga
    'bayern munich': 'munich',
    'fc bayern': 'munich',
    'borussia dortmund': 'dortmund',
    'schalke': 'gelsenkirchen',
    'schalke 04': 'gelsenkirchen',
    'hamburger': 'hamburg',
    'hamburger sv': 'hamburg',
    'hsv': 'hamburg',
    'werder': 'bremen',
    'werder bremen': 'bremen',
    'hertha': 'berlin',
    'hertha bsc': 'berlin',
    'union berlin': 'berlin',
    '1 fc union berlin': 'berlin',

    # Ligue 1
    'paris saint-germain': 'paris',
    'paris saint-germain fc': 'paris',
    'psg': 'paris',
    'paris fc': 'paris',
    'marseille': 'marseille',
    'olympique de marseille': 'marseille',
    'lyon': 'lyon',
    'olympique lyonnais': 'lyon',
    'nice': 'nice',
    'monaco': 'monaco',
    'as monaco': 'monaco',
    'lens': 'lens',
    'rc lens': 'lens',
    'lille': 'lille',
    'losc lille': 'lille',

    # Eredivisie
    'ajax': 'amsterdam',
    'psv': 'eindhoven',
    'psv eindhoven': 'eindhoven',
    'feyenoord': 'rotterdam',

    # Primeira Liga
    'benfica': 'lisbon',
    'sl benfica': 'lisbon',
    'sporting': 'lisbon',
    'sporting cp': 'lisbon',
    'porto': 'porto',
    'fc porto': 'porto',
}

# Города с несколькими клубами (реальные дерби)
DERBY_CITIES = {
    'manchester', 'london', 'liverpool', 'birmingham', 'sheffield',
    'madrid', 'barcelona', 'sevilla', 'milan', 'rome', 'turin',
    'gelsenkirchen_dortmund',  # Рурское дерби — специальный случай
    'berlin', 'hamburg_bremen',  # Северное дерби — специальный случай
    'lisbon', 'porto',
    'amsterdam', 'rotterdam',  # De Klassieker
}

# Специальные дерби между городами (традиционные соперники)
# V7.5: ТОЧНЫЕ пары — не частичное совпадение!
INTERCITY_DERBIES = [
    # Bundesliga
    frozenset({'borussia dortmund', 'schalke 04'}),
    frozenset({'borussia dortmund', 'schalke'}),
    frozenset({'hamburger sv', 'werder bremen'}),
    frozenset({'hertha bsc', 'union berlin'}),
    # Eredivisie
    frozenset({'ajax', 'feyenoord'}),
    frozenset({'ajax', 'psv eindhoven'}),
    frozenset({'ajax', 'psv'}),
    # La Liga — ТОЛЬКО настоящие баскские дерби
    frozenset({'athletic club', 'real sociedad'}),  # Баскское дерби ТОЧНО
    frozenset({'athletic', 'real sociedad'}),
    # Premier League
    frozenset({'brighton', 'crystal palace'}),
    frozenset({'newcastle united', 'sunderland'}),
    frozenset({'newcastle', 'sunderland'}),
]


def is_derby(home_name, away_name):
    """
    V7.5: ИСПРАВЛЕННЫЙ детектор дерби

    V7.4 баг: Atlético de Madrid vs Real Sociedad = ложное дерби
    Причина: INTERCITY_DERBIES проверял если ОДНА из команд совпадает
    V7.5 fix: проверяем только ТОЧНУЮ пару обеих команд

    Returns: bool
    """
    h = _normalize(home_name)
    a = _normalize(away_name)

    # 1. Проверяем межгородские дерби — ТОЛЬКО точная пара обеих команд
    for derby_pair in INTERCITY_DERBIES:
        dp = list(derby_pair)
        if len(dp) == 2:
            t1, t2 = dp[0], dp[1]
            # V7.5: точное совпадение ОБЕИХ команд, не одной!
            home_match_t1 = (t1 == h or t1 in h or h in t1)
            away_match_t2 = (t2 == a or t2 in a or a in t2)
            home_match_t2 = (t2 == h or t2 in h or h in t2)
            away_match_t1 = (t1 == a or t1 in a or a in t1)

            if (home_match_t1 and away_match_t2) or (home_match_t2 and away_match_t1):
                return True

    # 2. Находим города обеих команд
    home_city = _find_city(h)
    away_city = _find_city(a)

    # 3. Оба города найдены И одинаковые → дерби
    if home_city and away_city and home_city == away_city:
        if home_city in DERBY_CITIES:
            return True

    return False


def _find_city(normalized_name):
    """Найти город команды по нормализованному имени"""
    # Точное совпадение
    if normalized_name in TEAM_CITY:
        return TEAM_CITY[normalized_name]

    # Частичное совпадение
    for team, city in TEAM_CITY.items():
        if team in normalized_name or normalized_name in team:
            return city
        # Совпадение ключевых слов
        team_words = set(w for w in team.split() if len(w) > 3)
        name_words = set(w for w in normalized_name.split() if len(w) > 3)
        if team_words and name_words and team_words & name_words:
            return city

    return None


def _soft_match(name, pattern):
    """Мягкое совпадение имён"""
    return pattern in name or name in pattern or \
           any(w in name for w in pattern.split() if len(w) > 4)


# ============================================================
# V7.4: ФЛАГ ЗОНЫ ВЫЛЕТА (ГЛАВНОЕ ИСПРАВЛЕНИЕ!)
# ============================================================

def check_relegation_context(home_pos, away_pos, total_teams=20):
    """
    V7.4: Анализ контекста зоны вылета

    ПРОБЛЕМА V7.3: 5/5 матчей с командой 15-20 места дали сюрприз!
    - Wolves (20) vs Liverpool (5): 2:1 — аутсайдер победил дома
    - Man City (2) vs Nott'm F (17): 2:2 — ничья вместо победы
    - West Ham (18) в Fulham (10): 0:1 — аутсайдер победил в гостях
    - Leeds (15) vs Sunderland (12): 0:1 — проиграли дома

    Returns:
        dict с корректировками или None если нет зоны вылета
    """
    if not home_pos or not away_pos:
        return None

    relegation_zone = total_teams - 5  # 15 для 20 команд

    home_relegation = home_pos >= relegation_zone
    away_relegation = away_pos >= relegation_zone

    if not home_relegation and not away_relegation:
        return None  # Нет команд из зоны вылета

    result = {
        'home_relegation': home_relegation,
        'away_relegation': away_relegation,
        'confidence_penalty': 0,
        'draw_bonus': 0,
        'home_bonus': 0,
        'warning': '',
        'flag': False,
    }

    if home_relegation and away_relegation:
        # Оба в зоне вылета — хозяева ОЧЕНЬ мотивированы дома
        result.update({
            'confidence_penalty': 5,
            'draw_bonus': 3,
            'home_bonus': 10,  # Хозяева усилены — матч выживания дома!
            'warning': '⚠️ Оба в зоне вылета! Хозяева максимально мотивированы дома',
            'flag': True,
        })
    elif home_relegation:
        # Хозяева в зоне вылета — играют как в финале сезона
        result.update({
            'confidence_penalty': 15,  # V7.3: Man City не смог выиграть у Nott'm F
            'draw_bonus': 5,
            'home_bonus': 8,
            'warning': f'⚠️ Хозяева ({home_pos} место) — зона вылета! Сверхмотивация!',
            'flag': True,
        })
    else:
        # Гости в зоне вылета — отчаянная игра в гостях
        result.update({
            'confidence_penalty': 10,  # V7.3: West Ham выиграл в гостях у Fulham
            'draw_bonus': 5,
            'home_bonus': -5,
            'warning': f'⚠️ Гости ({away_pos} место) — зона вылета! Ничего терять!',
            'flag': True,
        })

    return result


# ============================================================
# V7.4: КОНТЕКСТ ЕВРОКУБКОВОЙ ЗОНЫ
# ============================================================

def check_european_context(home_pos, away_pos):
    """
    V7.4: Если обе команды в топ-7 → атакующий матч!

    ПРОБЛЕМА V7.3: Aston Villa (4) vs Chelsea (6) → X=42%, итог 1:4
    Обе команды борются за Европу → нужны победы → атака, не осторожность

    Returns:
        dict с корректировками или None
    """
    if not home_pos or not away_pos:
        return None

    euro_zone = 7
    both_european = home_pos <= euro_zone and away_pos <= euro_zone

    if not both_european:
        return None

    return {
        'draw_penalty': 8,    # X -8% (не осторожный матч!)
        'over_bonus': 8,      # ТБ +8% (атакующий матч)
        'confidence_bonus': 3,
        'note': f'🇪🇺 Оба в зоне еврокубков ({home_pos} vs {away_pos} место) — атакующий матч',
    }


# ============================================================
# V7.4: ЛИДЕР В ГОСТЯХ = ТМ
# ============================================================

def check_leader_away(home_pos, away_pos):
    """
    V7.5: Лидер чемпионата в гостях → ПОЛНЫЙ ЗАПРЕТ ТБ (было -10%)

    Паттерн 2/2 в тестах:
    - Arsenal (1) в гостях → 0:1
    - Barcelona (1) в гостях → 0:1
    V7.4 давал -10% — недостаточно, ТБ всё равно рекомендовался
    V7.5: возвращаем флаг block_over=True → ТБ не рекомендуется вообще
    """
    if not home_pos or not away_pos:
        return None

    if away_pos <= 2:
        return {
            'under_bonus': 15,
            'over_penalty': 15,
            'block_over': True,   # V7.5: ПОЛНЫЙ ЗАПРЕТ ТБ
            'note': f'👑 Лидер ({away_pos} место) в гостях — осторожная тактика → ТМ',
        }
    if away_pos == 3:
        return {
            'under_bonus': 8,
            'over_penalty': 8,
            'block_over': False,
            'note': f'👑 Топ-3 ({away_pos} место) в гостях',
        }
    return None


# ============================================================
# V7.5: РЕЖИМ ЕВРОКУБКОВ
# ============================================================

EURO_CUP_LEAGUES = {'CL', 'EL', 'ECL'}  # ЛЧ, ЛЕ, Лига Конференций

def is_euro_cup(league_code):
    """Проверить является ли лига еврокубковой"""
    return league_code in EURO_CUP_LEAGUES


def analyze_euro_cup_match(home, away, odds, xg_data, h2h):
    """
    V7.5: Специальный анализ для еврокубков (ЛЧ/ЛЕ)

    В еврокубковом плей-офф:
    - Таблица нацчемпионата НЕРЕЛЕВАНТНА
    - Galatasaray 20 место в Турции ≠ слабая команда в ЛЧ
    - Обе команды прошли отбор → примерно равны по классу
    - Плей-офф = кубковый матч → высокая мотивация обеих команд
    - Тактика: первая нога = осторожно, вторая = нужен результат

    Используем только: форму, xG, H2H, коэффициенты
    """
    scores = {'home_win': 0, 'draw': 0, 'away_win': 0, 'over_25': 0, 'btts': 0}
    factors = {'home_win': [], 'draw': [], 'away_win': [], 'over_25': [], 'btts': []}

    # Базовое домашнее преимущество (в ЛЧ меньше чем в нацлиге)
    scores['home_win'] += 7

    # Форма
    hw = home['last_5'].count('W')
    aw = away['last_5'].count('W')
    if hw >= 4: scores['home_win'] += 20; factors['home_win'].append(f"🔥 Форма {hw}/5")
    elif hw >= 3: scores['home_win'] += 12; factors['home_win'].append(f"✅ Форма {hw}/5")
    elif hw <= 1: scores['away_win'] += 8
    if aw >= 4: scores['away_win'] += 20; factors['away_win'].append(f"🔥 Форма гостей {aw}/5")
    elif aw >= 3: scores['away_win'] += 12; factors['away_win'].append(f"✅ Форма гостей {aw}/5")
    if hw == 2 and aw == 2:
        scores['draw'] += 15; factors['draw'].append("⚖️ Равная форма")

    # xG
    if xg_data:
        home_xg = xg_data.get('home', {})
        away_xg = xg_data.get('away', {})
        if home_xg and away_xg:
            hxg = home_xg.get('xG_for', 1.5)
            axg = away_xg.get('xG_for', 1.5)
            if hxg > 2.0: scores['home_win'] += 20; scores['over_25'] += 15
            elif hxg > 1.5: scores['home_win'] += 12
            if axg > 2.0: scores['away_win'] += 20; scores['over_25'] += 15
            elif axg > 1.5: scores['away_win'] += 12
            total_xg = (hxg + axg) / 2
            if total_xg > 2.5:
                scores['over_25'] += 20
                factors['over_25'].append(f"⚽ Средний xG {total_xg:.1f}")
            elif total_xg < 1.8:
                scores['over_25'] -= 10

    # Голы
    avg_goals = (home['goals_avg'] + away['goals_avg']) / 2
    if avg_goals > 2.5:
        scores['over_25'] += 15
        factors['over_25'].append(f"🎯 Среднее голов {avg_goals:.1f}")
    elif avg_goals < 1.8:
        scores['over_25'] -= 10
    if home['goals_avg'] >= 1.2 and away['goals_avg'] >= 1.2:
        scores['btts'] += 20

    # H2H
    if h2h and h2h['total'] >= 2:
        if h2h['avg_goals'] > 2.8:
            scores['over_25'] += 15
            factors['over_25'].append(f"🔁 H2H голов/матч: {h2h['avg_goals']}")
        if h2h['home_wins'] > h2h['away_wins'] * 1.5:
            scores['home_win'] += 10
            factors['home_win'].append(f"🔁 H2H перевес хозяев")
        elif h2h['away_wins'] > h2h['home_wins'] * 1.5:
            scores['away_win'] += 10
            factors['away_win'].append(f"🔁 H2H перевес гостей")

    # Коэффициенты (самый важный источник для ЛЧ!)
    if odds:
        if odds.get('home_win') and odds.get('draw') and odds.get('away_win'):
            mh = odds_to_prob(odds['home_win'])
            md = odds_to_prob(odds['draw'])
            ma = odds_to_prob(odds['away_win'])
            # В ЛЧ рынок очень хорошо калиброван → даём больший вес
            scores['home_win'] += mh * 0.5
            scores['draw'] += md * 0.5
            scores['away_win'] += ma * 0.5
            if mh > 55: factors['home_win'].append(f"💰 Рынок: {mh}% за хозяев")
            if ma > 55: factors['away_win'].append(f"💰 Рынок: {ma}% за гостей")
            if md > 30: factors['draw'].append(f"💰 Рынок ждёт ничью")
        if odds.get('over_25') and odds.get('under_25'):
            om = odds_to_prob(odds['over_25'])
            if om > 55:
                scores['over_25'] += 20
                factors['over_25'].append(f"💰 Рынок ТБ2.5: {om}%")
            elif om < 40:
                scores['over_25'] -= 15

    # Финальный расчёт
    total = scores['home_win'] + scores['draw'] + scores['away_win']
    if total <= 0: total = 100

    probs = {
        'home_win': round((scores['home_win'] / total) * 100, 1),
        'draw':     round((scores['draw'] / total) * 100, 1),
        'away_win': round((scores['away_win'] / total) * 100, 1),
    }
    over_base = 50 + scores['over_25'] * 0.3
    probs['over_25']  = round(min(85, max(15, over_base)), 1)
    probs['under_25'] = round(100 - probs['over_25'], 1)
    btts_base = 50 + scores['btts'] * 0.3
    probs['btts_yes'] = round(min(85, max(15, btts_base)), 1)
    probs['btts_no']  = round(100 - probs['btts_yes'], 1)

    # ML поверх
    ml = ml_predict(home, away, h2h, xg_data)
    blend = 0.70  # В ЛЧ чуть меньше доверия ML (нет данных таблицы)
    probs['home_win'] = round(probs['home_win'] * (1-blend) + ml['home_win'] * blend, 1)
    probs['away_win'] = round(probs['away_win'] * (1-blend) + ml['away_win'] * blend, 1)
    probs['draw']     = round(100 - probs['home_win'] - probs['away_win'], 1)
    probs['over_25']  = round(probs['over_25'] * (1-blend) + ml['over_25'] * blend, 1)
    probs['under_25'] = round(100 - probs['over_25'], 1)

    # Дерби X адаптация (для ЛЧ тоже)
    if is_derby(home['name'], away['name']):
        probs['draw'] = max(probs['draw'], 32.0)

    # Нормализация
    total_norm = probs['home_win'] + probs['draw'] + probs['away_win']
    if abs(total_norm - 100) > 0.5:
        diff = 100 - total_norm
        probs['home_win'] = round(probs['home_win'] + diff * 0.5, 1)
        probs['away_win'] = round(probs['away_win'] + diff * 0.5, 1)

    # Уверенность для ЛЧ — ограничена (высокая непредсказуемость)
    best_prob = max(probs['home_win'], probs['draw'], probs['away_win'])
    conf = min(70, max(55, int(best_prob * 0.85)))

    # Лучшая ставка для ЛЧ
    best = _find_best_bet_euro(probs, factors, odds, home, away)

    return {
        'probs': probs, 'confidence': conf,
        'best_bet': best, 'factors': factors,
        'xg_used': xg_data is not None,
        'odds_used': odds is not None,
        'h2h': h2h, 'ml': ml,
        'standings': None,
        'home_congestion': None,
        'away_congestion': None,
        'match_classification': {
            'match_class': 'EURO_CUP',
            'gap': 0, 'is_derby': is_derby(home['name'], away['name']),
            'recommendation': 'BET',
            'reason': '🏆 Еврокубок — таблица нерелевантна',
        },
        'home_pos': None, 'away_pos': None,
        'relegation_ctx': None,
        'european_ctx': None,
        'leader_away_ctx': None,
        'is_euro_cup': True,
    }


def _find_best_bet_euro(probs, factors, odds, home, away):
    """Поиск лучшей ставки для еврокубков"""
    candidates = []

    # Исход — только при высокой уверенности (ЛЧ непредсказуем)
    for key, label, odds_key in [
        ('home_win', f"П1 {home['name']}", 'home_win'),
        ('away_win', f"П2 {away['name']}", 'away_win'),
    ]:
        if probs[key] >= 60:  # Строже чем в нацлиге
            value = 0
            odds_val = None
            if odds and odds.get(odds_key):
                mp = odds_to_prob(odds[odds_key])
                value = probs[key] - mp
                odds_val = odds[odds_key]
            candidates.append({
                'type': label, 'prob': probs[key], 'odds': odds_val,
                'value': value, 'factors': factors.get(key, []),
                'score': probs[key] + max(0, value) * 2,
                'warning': '🏆 Еврокубок — повышенная непредсказуемость',
            })

    # ТБ для ЛЧ — порог 65% (было 68% — Real Madrid-ManCity 67.9% не прошёл при 3 голах!)
    if probs['over_25'] >= 65:
        candidates.append({
            'type': 'ТБ 2.5', 'prob': probs['over_25'],
            'odds': odds.get('over_25') if odds else None,
            'value': 0, 'factors': factors.get('over_25', []),
            'score': probs['over_25'],
            'warning': None,
        })

    # X при высокой вероятности
    if probs['draw'] >= 38:
        candidates.append({
            'type': 'X (Ничья)', 'prob': probs['draw'],
            'odds': odds.get('draw') if odds else None,
            'value': 0, 'factors': factors.get('draw', []),
            'score': probs['draw'],
            'warning': '🏆 Еврокубок — ничья частый результат',
        })

    if not candidates:
        return {
            'type': None, 'prob': 0,
            'warning': '🏆 Нет чёткого сигнала — еврокубок, рекомендуем ПРОПУСТИТЬ',
        }

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[0]


# ============================================================
# V7.3 БАЗА (без изменений)
# ============================================================

def classify_match(home_pos, away_pos, home_name, away_name):
    """Классификация матча по типу"""
    gap = abs(home_pos - away_pos) if home_pos and away_pos else 0
    derby = is_derby(home_name, away_name)

    if derby:
        return {
            'match_class': 'DERBY', 'gap': gap, 'is_derby': True,
            'recommendation': 'SKIP',
            'reason': 'Дерби! Высокая непредсказуемость. Реальная X = 35-40%',
        }
    if gap > 10:
        return {
            'match_class': 'CLEAR_FAVORITE', 'gap': gap, 'is_derby': False,
            'recommendation': 'BET',
            'reason': f'Явный фаворит (разница {gap} позиций)',
        }
    if gap >= 5:
        return {
            'match_class': 'MEDIUM_FAVORITE', 'gap': gap, 'is_derby': False,
            'recommendation': 'CAUTION',
            'reason': f'Средний фаворит (разница {gap} позиций)',
        }
    return {
        'match_class': 'CLOSE', 'gap': gap, 'is_derby': False,
        'recommendation': 'SKIP',
        'reason': f'Близкие команды (разница {gap} позиций). Высокая X ~40-45%',
    }


def classify_match_fallback(home_name, away_name, odds=None, ml=None):
    """
    V7.6: Классификация матча БЕЗ таблицы (standings=None)

    Раньше: home_pos or 10 → gap=0 → "Близкие команды" → БРЕД
    Теперь: используем коэффициенты и ML для определения фаворита

    Логика коэффициентов:
    - П1 @ 1.30-1.50 = ~67-77% → CLEAR_FAVORITE
    - П1 @ 1.50-1.80 = ~56-67% → MEDIUM_FAVORITE
    - П1/П2 @ 1.80-2.20 = ~45-56% → CLOSE
    - дерби → DERBY (по городу, как раньше)
    """
    # Сначала проверяем дерби (работает без таблицы)
    if is_derby(home_name, away_name):
        return {
            'match_class': 'DERBY', 'gap': 0, 'is_derby': True,
            'recommendation': 'SKIP',
            'reason': 'Дерби! Высокая непредсказуемость.',
            'fallback': True,
        }

    # Если есть коэффициенты — используем их
    if odds and odds.get('home_win') and odds.get('away_win'):
        home_prob = odds_to_prob(odds['home_win'])
        away_prob = odds_to_prob(odds['away_win'])
        best_prob = max(home_prob, away_prob)
        is_home_fav = home_prob >= away_prob

        if best_prob >= 67:  # @ ~1.50 и ниже
            return {
                'match_class': 'CLEAR_FAVORITE', 'gap': 15, 'is_derby': False,
                'recommendation': 'BET',
                'reason': f'Явный фаворит по коэффициентам ({best_prob:.0f}%)',
                'fallback': True,
                'home_fav': is_home_fav,
            }
        elif best_prob >= 55:  # @ ~1.80 и ниже
            return {
                'match_class': 'MEDIUM_FAVORITE', 'gap': 7, 'is_derby': False,
                'recommendation': 'CAUTION',
                'reason': f'Средний фаворит по коэффициентам ({best_prob:.0f}%)',
                'fallback': True,
                'home_fav': is_home_fav,
            }
        else:
            return {
                'match_class': 'CLOSE', 'gap': 2, 'is_derby': False,
                'recommendation': 'SKIP',
                'reason': f'Равные команды по коэффициентам',
                'fallback': True,
                'home_fav': is_home_fav,
            }

    # Если есть ML — используем его
    if ml:
        best_ml = max(ml['home_win'], ml['away_win'])
        is_home_fav = ml['home_win'] >= ml['away_win']
        if best_ml >= 65:
            return {
                'match_class': 'CLEAR_FAVORITE', 'gap': 15, 'is_derby': False,
                'recommendation': 'BET',
                'reason': f'Явный фаворит по ML ({best_ml:.0f}%)',
                'fallback': True,
                'home_fav': is_home_fav,
            }
        elif best_ml >= 52:
            return {
                'match_class': 'MEDIUM_FAVORITE', 'gap': 7, 'is_derby': False,
                'recommendation': 'CAUTION',
                'reason': f'Средний фаворит по ML ({best_ml:.0f}%)',
                'fallback': True,
                'home_fav': is_home_fav,
            }

    # Нет ни таблицы, ни коэффициентов, ни ML → ПРОПУСТИТЬ
    return {
        'match_class': 'CLOSE', 'gap': 0, 'is_derby': False,
        'recommendation': 'SKIP',
        'reason': 'Недостаточно данных для анализа',
        'fallback': True,
        'home_fav': True,
    }


def calculate_adaptive_draw_probability(match_classification, base_draw,
                                         home_pos=None, away_pos=None):
    """V7.3 адаптивная X — без изменений, работает хорошо"""
    match_class = match_classification['match_class']
    gap = match_classification['gap']

    if match_class == 'DERBY':
        return 32.0 if gap > 10 else (36.0 if gap > 5 else 40.0)
    elif match_class == 'CLOSE':
        return 42.0 if gap <= 2 else (38.0 if gap <= 4 else 34.0)
    elif match_class == 'MEDIUM_FAVORITE':
        return 28.0 if gap <= 6 else (25.0 if gap <= 8 else 22.0)
    else:  # CLEAR_FAVORITE
        return max(12.0, min(18.0, base_draw))


def calculate_dynamic_confidence_v74(probs, factors, ml_prob, match_classification,
                                      relegation_ctx=None):
    """
    V7.4: Уверенность с учётом зоны вылета

    Новое vs V7.3:
    - Зона вылета (любая): -10-15% к уверенности
    - Логика максимумов без изменений (работает)
    """
    match_class = match_classification['match_class']
    best_prob = max(probs['home_win'], probs['draw'], probs['away_win'])
    confidence = best_prob

    # Согласие ML
    main_winner = max(probs, key=probs.get)
    ml_map = {'home_win': ml_prob['home_win'], 'draw': ml_prob['draw'],
               'away_win': ml_prob['away_win']}
    ml_winner = max(ml_map, key=ml_map.get)

    if main_winner == ml_winner:
        diff = abs(probs[main_winner] - ml_map[ml_winner])
        confidence += 10 if diff < 5 else (5 if diff < 10 else 0)
    else:
        confidence -= 10

    # Явность фаворита
    sorted_probs = sorted(probs.values(), reverse=True)
    gap = sorted_probs[0] - sorted_probs[1]
    confidence += 5 if gap > 30 else (-5 if gap < 15 else 0)

    # Факторы
    winner_factors = factors.get(main_winner, [])
    confidence += 5 if len(winner_factors) >= 4 else (-5 if len(winner_factors) <= 1 else 0)

    # V7.4: ШТРАФ ЗОНЫ ВЫЛЕТА
    if relegation_ctx and relegation_ctx.get('flag'):
        confidence -= relegation_ctx['confidence_penalty']

    # Ограничение по типу матча (V7.3 — работает)
    if match_class == 'DERBY':
        max_conf, min_conf = 60, 55
    elif match_class == 'CLOSE':
        max_conf, min_conf = 62, 55
    elif match_class == 'MEDIUM_FAVORITE':
        max_conf, min_conf = 68, 58
    else:  # CLEAR_FAVORITE
        # V7.4: если есть зона вылета — снизить максимум
        if relegation_ctx and relegation_ctx.get('flag'):
            max_conf, min_conf = 72, 60  # Было 85
        else:
            max_conf, min_conf = 85, 62

    return min(max_conf, max(min_conf, int(confidence)))


# ============ ПОЛУЧЕНИЕ ДАННЫХ (без изменений) ============

def fd_request(endpoint, params=None):
    try:
        time.sleep(REQUEST_DELAY)
        r = requests.get(
            f"{FOOTBALLDATA_BASE_URL}/{endpoint}",
            headers={'X-Auth-Token': FOOTBALLDATA_API_KEY},
            params=params, timeout=10
        )
        return r.json() if r.status_code == 200 else None
    except:
        return None


def get_team_stats(team_id, team_name):
    data = fd_request(f'teams/{team_id}/matches', {'status': 'FINISHED', 'limit': 10})
    if not data or 'matches' not in data:
        return _default_stats(team_name)
    matches = data['matches']
    if not matches:
        return _default_stats(team_name)

    wins = draws = losses = gf = ga = 0
    form = []
    clean_sheets = over_25_count = btts_count = 0

    for m in matches[:10]:
        hs = m['score']['fullTime']['home'] or 0
        as_ = m['score']['fullTime']['away'] or 0
        is_home = m['homeTeam']['id'] == team_id
        scored = hs if is_home else as_
        conceded = as_ if is_home else hs
        gf += scored; ga += conceded
        if hs + as_ > 2.5: over_25_count += 1
        if hs > 0 and as_ > 0: btts_count += 1
        if conceded == 0: clean_sheets += 1
        if scored > conceded: wins += 1; form.append('W')
        elif scored < conceded: losses += 1; form.append('L')
        else: draws += 1; form.append('D')

    total = len(matches)
    return {
        'name': team_name, 'form': form[:5],
        'goals_avg': round(gf / total, 2) if total else 0,
        'conceded_avg': round(ga / total, 2) if total else 0,
        'wins': wins, 'draws': draws, 'losses': losses,
        'win_pct': round((wins / total) * 100) if total else 0,
        'clean_sheets': clean_sheets, 'last_5': form[:5],
        'over_25_pct': round((over_25_count / total) * 100) if total else 50,
        'btts_pct': round((btts_count / total) * 100) if total else 45,
    }


def _default_stats(name):
    return {
        'name': name, 'form': [], 'goals_avg': 1.5, 'conceded_avg': 1.5,
        'wins': 0, 'draws': 0, 'losses': 0, 'win_pct': 50,
        'clean_sheets': 0, 'last_5': [],
        'over_25_pct': 50, 'btts_pct': 45,
    }


def get_xg_data(league_code, home_team, away_team):
    league_key = UNDERSTAT_LEAGUES.get(league_code)
    if not league_key:
        return None
    try:
        url = f"https://understat.com/league/{league_key}/2025"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        pattern = r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)"
        match = re.search(pattern, r.text)
        if not match:
            return None
        raw = match.group(1).encode('utf-8').decode('unicode_escape')
        teams_data = json.loads(raw)
        result = {}
        for _, team_info in teams_data.items():
            name = team_info.get('title', '')
            for our_team, key in [(home_team, 'home'), (away_team, 'away')]:
                if _teams_match(our_team, name):
                    history = team_info.get('history', [])[-10:]
                    if history:
                        xg_for = sum(float(m.get('xG', 0)) for m in history) / len(history)
                        xg_against = sum(float(m.get('xGA', 0)) for m in history) / len(history)
                        result[key] = {'xG_for': round(xg_for, 2),
                                       'xG_against': round(xg_against, 2)}
        return result if result else None
    except Exception as e:
        logger.debug(f"xG error: {e}")
        return None


def get_odds(league_code, home_team, away_team):
    if not ODDS_API_KEY or league_code not in ODDS_LEAGUES:
        return None
    try:
        sport_key = ODDS_LEAGUES[league_code]
        r = requests.get(
            f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds/",
            params={'apiKey': ODDS_API_KEY, 'regions': 'eu',
                    'markets': 'h2h,totals,btts', 'oddsFormat': 'decimal'},
            timeout=15
        )
        if r.status_code != 200:
            return None
        for game in r.json():
            h = game.get('home_team', '')
            a = game.get('away_team', '')
            if _teams_match(home_team, h) and _teams_match(away_team, a):
                if not game.get('bookmakers'):
                    continue
                bm = game['bookmakers'][0]
                result = {'bookmaker': bm['title']}
                for market in bm['markets']:
                    if market['key'] == 'h2h':
                        for o in market['outcomes']:
                            if o['name'] == game['home_team']: result['home_win'] = o['price']
                            elif o['name'] == game['away_team']: result['away_win'] = o['price']
                            elif o['name'] == 'Draw': result['draw'] = o['price']
                    elif market['key'] == 'totals':
                        for o in market['outcomes']:
                            if o.get('point') == 2.5:
                                if o['name'] == 'Over': result['over_25'] = o['price']
                                elif o['name'] == 'Under': result['under_25'] = o['price']
                    elif market['key'] == 'btts':
                        for o in market['outcomes']:
                            if o['name'] == 'Yes': result['btts_yes'] = o['price']
                            elif o['name'] == 'No': result['btts_no'] = o['price']
                return result
    except Exception as e:
        logger.warning(f"Odds error: {e}")
    return None


def get_h2h(home_id, away_id):
    try:
        data = fd_request(f'teams/{home_id}/matches', {'status': 'FINISHED', 'limit': 30})
        if not data or 'matches' not in data:
            return None
        h2h = [m for m in data['matches']
               if (m['homeTeam']['id'] == home_id and m['awayTeam']['id'] == away_id) or
                  (m['homeTeam']['id'] == away_id and m['awayTeam']['id'] == home_id)]
        if len(h2h) < 2:
            return None
        home_w = draws = away_w = total_goals = btts_c = 0
        for m in h2h[:8]:
            hs = m['score']['fullTime']['home'] or 0
            as_ = m['score']['fullTime']['away'] or 0
            total_goals += hs + as_
            if hs > 0 and as_ > 0: btts_c += 1
            is_home = m['homeTeam']['id'] == home_id
            scored = hs if is_home else as_
            conceded = as_ if is_home else hs
            if scored > conceded: home_w += 1
            elif scored < conceded: away_w += 1
            else: draws += 1
        total = len(h2h[:8])
        return {
            'total': total, 'home_wins': home_w, 'draws': draws, 'away_wins': away_w,
            'avg_goals': round(total_goals / total, 1) if total else 2.5,
            'btts_pct': round((btts_c / total) * 100) if total else 50,
            'home_win_pct': round((home_w / total) * 100) if total else 33,
        }
    except Exception as e:
        logger.debug(f"H2H error: {e}")
        return None


def get_standings(league_code):
    try:
        data = fd_request(f'competitions/{league_code}/standings', {})
        if not data or 'standings' not in data:
            return None
        table = data['standings'][0] if data['standings'] else None
        if not table or 'table' not in table:
            return None
        positions = {}
        for entry in table['table']:
            team = entry.get('team', {})
            positions[team.get('id')] = {
                'position': entry.get('position', 99),
                'points': entry.get('points', 0),
                'played': entry.get('playedGames', 0),
            }
        return positions
    except:
        return None


def analyze_table_context(position, total_teams=20):
    if position >= 15:
        return {'motivation': 3, 'context': 'Зона вылета',
                'description': 'Борьба за выживание!'}
    elif position <= 3:
        return {'motivation': 2, 'context': 'Борьба за титул',
                'description': 'Погоня за чемпионством'}
    elif position <= 7:
        return {'motivation': 2, 'context': 'Зона еврокубков',
                'description': 'Борьба за Европу'}
    else:
        return {'motivation': 0, 'context': 'Середина таблицы',
                'description': 'Спокойная позиция'}


def check_fixture_congestion(team_id):
    try:
        data = fd_request(f'teams/{team_id}/matches', {'status': 'FINISHED', 'limit': 5})
        if not data or 'matches' not in data:
            return {'days_rest': 7, 'fatigue_factor': 0}
        matches = data['matches']
        if not matches:
            return {'days_rest': 7, 'fatigue_factor': 0}
        last_match = matches[0]
        last_date = datetime.fromisoformat(last_match['utcDate'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        days_rest = (now - last_date).days
        if days_rest <= 2: fatigue = 3
        elif days_rest <= 4: fatigue = 2
        elif days_rest <= 6: fatigue = 1
        else: fatigue = 0
        return {'days_rest': days_rest, 'fatigue_factor': fatigue}
    except:
        return {'days_rest': 7, 'fatigue_factor': 0}


def ml_predict(home, away, h2h, xg_data):
    import math

    def sigmoid(x):
        return 1 / (1 + math.exp(-max(-10, min(10, x))))

    hw = home['last_5'].count('W')
    aw = away['last_5'].count('W')
    f_form = (hw - aw) / 5.0
    f_goals = (home['goals_avg'] - away['goals_avg']) / 3.0
    f_defense = (away['conceded_avg'] - home['conceded_avg']) / 3.0
    f_winpct = (home['win_pct'] - away['win_pct']) / 100.0

    if xg_data and xg_data.get('home') and xg_data.get('away'):
        hxg = xg_data['home'].get('xG_for', home['goals_avg'])
        axg = xg_data['away'].get('xG_for', away['goals_avg'])
        f_xg = (hxg - axg) / 3.0
    else:
        f_xg = f_goals

    f_h2h = 0.0
    if h2h and h2h['total'] >= 3:
        f_h2h = (h2h['home_wins'] - h2h['away_wins']) / max(h2h['total'], 1)

    z = 0.4 + 2.5*f_xg + 2.1*f_form + 1.8*f_goals + 1.6*f_defense + 1.4*f_winpct + 1.2*f_h2h
    home_raw = sigmoid(z)
    gap = abs(f_form) + abs(f_xg)
    draw_p = max(0.10, 0.27 - gap * 0.12)
    home_p = round(home_raw * (1 - draw_p) * 100, 1)
    away_p = round((1 - home_raw) * (1 - draw_p) * 100, 1)
    draw_p2 = round(100 - home_p - away_p, 1)

    exp_goals = home['goals_avg'] + away['goals_avg']
    if xg_data and xg_data.get('home') and xg_data.get('away'):
        xg_sum = xg_data['home'].get('xG_for', 0) + xg_data['away'].get('xG_for', 0)
        exp_goals = (exp_goals + xg_sum) / 2

    over_p = round(sigmoid((exp_goals - 2.5) * 1.2) * 100, 1)
    return {
        'home_win': home_p, 'draw': draw_p2, 'away_win': away_p,
        'over_25': over_p, 'conf_boost': min(15, round(abs(z) * 4)),
    }


def _normalize(name):
    name = name.lower().strip()
    for s in [' fc', ' cf', ' sc', ' ac', ' afc', ' fk', ' sk', ' if', ' bk',
              ' united', ' city', ' town', ' athletic', ' albion', ' hotspur',
              ' wanderers', ' rovers', ' county', ' palace', ' villa']:
        if name.endswith(s):
            name = name[:-len(s)]
    return name.replace('.', '').replace('-', ' ').replace("'", '').strip()


def _teams_match(t1, t2):
    n1, n2 = _normalize(t1), _normalize(t2)
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    w1 = set(w for w in n1.split() if len(w) > 3)
    w2 = set(w for w in n2.split() if len(w) > 3)
    return bool(w1 & w2)


def odds_to_prob(odds):
    if not odds or odds <= 1:
        return 0
    return round((1 / odds) * 100, 1)


# ============================================================
# V7.4: ГЛАВНЫЙ АНАЛИЗАТОР
# ============================================================

def mega_analysis_v74(home, away, odds, xg_data, league_code, h2h=None,
                       standings=None, home_congestion=None, away_congestion=None):
    """
    V7.5: Главный анализатор
    Еврокубки → отдельная логика без таблицы нацчемпионата
    """
    # V7.5: РЕЖИМ ЕВРОКУБКОВ
    if is_euro_cup(league_code):
        result = analyze_euro_cup_match(home, away, odds, xg_data, h2h)
        result['home_congestion'] = home_congestion
        result['away_congestion'] = away_congestion
        return result

    scores = {'home_win': 0, 'draw': 0, 'away_win': 0, 'over_25': 0, 'btts': 0}
    factors = {'home_win': [], 'draw': [], 'away_win': [], 'over_25': [], 'btts': []}

    # ── Позиции в таблице ──────────────────────────────────
    home_pos = away_pos = None
    if standings and home.get('id') and away.get('id'):
        hd = standings.get(home['id'])
        ad = standings.get(away['id'])
        if hd: home_pos = hd['position']
        if ad: away_pos = ad['position']

    # ── V7.6: Классификация с fallback ───────────────────
    if home_pos and away_pos:
        # Есть таблица → обычная классификация
        match_classification = classify_match(
            home_pos, away_pos,
            home['name'], away['name']
        )
    else:
        # V7.6: Нет таблицы → fallback по коэффициентам/ML
        # Сначала считаем быстрый ML для fallback
        quick_ml = ml_predict(home, away, h2h, xg_data)
        match_classification = classify_match_fallback(
            home['name'], away['name'], odds, quick_ml
        )
        logger.info(f"V7.6 FALLBACK классификация: {match_classification['reason']}")

    # ── V7.4/V7.6: Контексты ─────────────────────────────
    relegation_ctx   = check_relegation_context(home_pos, away_pos)
    european_ctx     = check_european_context(home_pos, away_pos)
    leader_away_ctx  = check_leader_away(home_pos, away_pos)

    match_class = match_classification['match_class']

    # ── V7.6: Зона вылета гостей перебивает CLOSE ─────────
    # Gladbach(12) vs St.Pauli(16): gap=4 → CLOSE → X
    # Реально: St.Pauli в зоне → Gladbach П1 2:0
    if (match_class == 'CLOSE' and relegation_ctx and
            relegation_ctx.get('away_relegation') and not relegation_ctx.get('home_relegation')):
        match_classification = {
            'match_class': 'MEDIUM_FAVORITE', 'gap': 5, 'is_derby': False,
            'recommendation': 'CAUTION',
            'reason': f'Гости в зоне вылета — хозяева фаворит несмотря на близкие позиции',
        }
        match_class = 'MEDIUM_FAVORITE'

    # ── V7.4: Применяем контекст зоны вылета ──────────────
    if relegation_ctx and relegation_ctx.get('flag'):
        home_bonus = relegation_ctx.get('home_bonus', 0)
        if home_bonus > 0:
            scores['home_win'] += home_bonus
            factors['home_win'].append(relegation_ctx['warning'])
        elif home_bonus < 0:
            scores['away_win'] += abs(home_bonus)
            factors['away_win'].append(relegation_ctx['warning'])
        # X бонус применяется позже при расчёте adaptive_draw

    # ── Мотивация ──────────────────────────────────────────
    if home_pos and away_pos:
        home_context = analyze_table_context(home_pos)
        away_context = analyze_table_context(away_pos)
        home_motivation = home_context['motivation']
        away_motivation = away_context['motivation']
        motivation_diff = (home_motivation - away_motivation) * 3
        if motivation_diff > 0:
            scores['home_win'] += int(motivation_diff)
            if home_context['context'] != 'Середина таблицы':
                factors['home_win'].append(f"🔥 {home_context['context']}")
        elif motivation_diff < 0:
            scores['away_win'] += int(abs(motivation_diff))
            if away_context['context'] != 'Середина таблицы':
                factors['away_win'].append(f"🔥 {away_context['context']} (гости)")

    # ── Усталость ─────────────────────────────────────────
    if home_congestion and home_congestion['fatigue_factor'] >= 2:
        scores['away_win'] += home_congestion['fatigue_factor'] * 7
        scores['home_win'] -= home_congestion['fatigue_factor'] * 3
        factors['away_win'].append(
            f"😴 Хозяева уставшие ({home_congestion['days_rest']}д отдыха)")
    if away_congestion and away_congestion['fatigue_factor'] >= 2:
        scores['home_win'] += away_congestion['fatigue_factor'] * 7
        scores['away_win'] -= away_congestion['fatigue_factor'] * 3
        factors['home_win'].append(
            f"😴 Гости уставшие ({away_congestion['days_rest']}д отдыха)")

    # ── Домашнее преимущество ──────────────────────────────
    scores['home_win'] += 10

    # ── Форма ─────────────────────────────────────────────
    hw = home['last_5'].count('W')
    aw = away['last_5'].count('W')
    if hw >= 4: scores['home_win'] += 20; factors['home_win'].append(f"🔥 Форма {hw}/5")
    elif hw >= 3: scores['home_win'] += 12; factors['home_win'].append(f"✅ Форма {hw}/5")
    elif hw <= 1: scores['away_win'] += 8
    if aw >= 4: scores['away_win'] += 20; factors['away_win'].append(f"🔥 Форма гостей {aw}/5")
    elif aw >= 3: scores['away_win'] += 12; factors['away_win'].append(f"✅ Форма гостей {aw}/5")
    if hw == 2 and aw == 2:
        scores['draw'] += 15; factors['draw'].append("⚖️ Равная форма команд")

    # ── xG ────────────────────────────────────────────────
    if xg_data:
        home_xg = xg_data.get('home', {})
        away_xg = xg_data.get('away', {})
        if home_xg and away_xg:
            hxg = home_xg.get('xG_for', 1.5)
            axg = away_xg.get('xG_for', 1.5)
            hxga = home_xg.get('xG_against', 1.5)
            axga = away_xg.get('xG_against', 1.5)
            if hxg > 2.0:
                scores['home_win'] += 20; scores['over_25'] += 15
                factors['home_win'].append(f"📈 xG атака {hxg}")
                factors['over_25'].append(f"📈 Высокий xG {hxg}")
            elif hxg > 1.5:
                scores['home_win'] += 12; factors['home_win'].append(f"📈 xG {hxg}")
            if axg > 2.0:
                scores['away_win'] += 20; scores['over_25'] += 15
                factors['away_win'].append(f"📈 xG гостей {axg}")
            elif axg > 1.5:
                scores['away_win'] += 12
            if hxga < 0.8:
                scores['home_win'] += 15; factors['home_win'].append(f"🛡 xG защита {hxga}")
            if axga < 0.8:
                scores['away_win'] += 15; factors['away_win'].append(f"🛡 xG защита гостей {axga}")
            total_xg = (hxg + axg) / 2
            if total_xg > 2.5:
                scores['over_25'] += 20; scores['btts'] += 15
                factors['over_25'].append(f"⚽ Средний xG {total_xg:.1f}")
            elif total_xg < 1.8:
                scores['over_25'] -= 10

    # ── Голы ──────────────────────────────────────────────
    avg_goals = (home['goals_avg'] + away['goals_avg']) / 2
    if home['goals_avg'] > 2.0:
        scores['home_win'] += 12; scores['over_25'] += 12
        factors['home_win'].append(f"⚽ Голов/матч {home['goals_avg']}")
    if away['goals_avg'] > 2.0:
        scores['away_win'] += 12; scores['over_25'] += 12
        factors['away_win'].append(f"⚽ Голов гостей {away['goals_avg']}")
    if avg_goals > 2.5:
        scores['over_25'] += 15; scores['btts'] += 12
        factors['over_25'].append(f"🎯 Среднее голов {avg_goals:.1f}")
    elif avg_goals < 1.8:
        scores['over_25'] -= 10
    if home['goals_avg'] >= 1.2 and away['goals_avg'] >= 1.2:
        scores['btts'] += 20; factors['btts'].append("⚽ Обе команды забивают регулярно")
    elif home['goals_avg'] >= 1.0 and away['goals_avg'] >= 1.0:
        scores['btts'] += 10
    avg_btts = (home['btts_pct'] + away['btts_pct']) / 2
    if avg_btts > 60: scores['btts'] += 12; factors['btts'].append(f"📊 BTTS в {avg_btts:.0f}%")
    elif avg_btts < 35: scores['btts'] -= 10
    avg_over = (home['over_25_pct'] + away['over_25_pct']) / 2
    if avg_over > 65: scores['over_25'] += 12; factors['over_25'].append(f"📊 ТБ2.5 в {avg_over:.0f}%")
    elif avg_over < 35: scores['over_25'] -= 10

    # ── Защита ────────────────────────────────────────────
    if home['conceded_avg'] < 0.8:
        scores['home_win'] += 15; factors['home_win'].append("🛡 Надёжная защита")
    elif home['conceded_avg'] > 2.0:
        scores['away_win'] += 10; scores['btts'] += 8
    if away['conceded_avg'] < 0.8:
        scores['away_win'] += 15; factors['away_win'].append("🛡 Защита гостей надёжна")
    elif away['conceded_avg'] > 2.0:
        scores['home_win'] += 10; scores['btts'] += 8
        factors['btts'].append("🎯 Гости пропускают много")

    # ── Коэффициенты ──────────────────────────────────────
    if odds:
        if odds.get('home_win') and odds.get('draw') and odds.get('away_win'):
            mh = odds_to_prob(odds['home_win'])
            md = odds_to_prob(odds['draw'])
            ma = odds_to_prob(odds['away_win'])
            scores['home_win'] += mh * 0.3
            scores['draw'] += md * 0.3
            scores['away_win'] += ma * 0.3
            if mh > 60: scores['home_win'] += 20; factors['home_win'].append(f"💰 Рынок: {mh}% за хозяев")
            if ma > 60: scores['away_win'] += 20; factors['away_win'].append(f"💰 Рынок: {ma}% за гостей")
            if md > 35: scores['draw'] += 15; factors['draw'].append("💰 Рынок ждёт ничью")
        if odds.get('btts_yes') and odds.get('btts_no'):
            bm = odds_to_prob(odds['btts_yes'])
            if bm > 55: scores['btts'] += 15; factors['btts'].append(f"💰 Рынок BTTS: {bm}%")
            elif bm < 40: scores['btts'] -= 10
        if odds.get('over_25') and odds.get('under_25'):
            om = odds_to_prob(odds['over_25'])
            if om > 55: scores['over_25'] += 15; factors['over_25'].append(f"💰 Рынок ТБ2.5: {om}%")
            elif om < 40: scores['over_25'] -= 10

    # ── Win% ──────────────────────────────────────────────
    if home['win_pct'] > 70: scores['home_win'] += 15; factors['home_win'].append(f"📊 Побед {home['win_pct']}%")
    if away['win_pct'] > 70: scores['away_win'] += 15; factors['away_win'].append(f"📊 Побед гостей {away['win_pct']}%")

    # ── H2H ───────────────────────────────────────────────
    if h2h and h2h['total'] >= 3:
        if h2h['home_wins'] > h2h['away_wins'] * 1.5:
            scores['home_win'] += 12
            factors['home_win'].append(f"🔁 H2H: {h2h['home_wins']}В-{h2h['draws']}Н-{h2h['away_wins']}П")
        elif h2h['away_wins'] > h2h['home_wins'] * 1.5:
            scores['away_win'] += 12
            factors['away_win'].append(f"🔁 H2H: {h2h['home_wins']}В-{h2h['draws']}Н-{h2h['away_wins']}П")
        else:
            factors['draw'].append(f"🔁 H2H равный: {h2h['home_wins']}-{h2h['draws']}-{h2h['away_wins']}")
        if h2h['avg_goals'] > 2.8:
            scores['over_25'] += 10; factors['over_25'].append(f"🔁 H2H голов/матч: {h2h['avg_goals']}")
        if h2h['btts_pct'] > 65:
            scores['btts'] += 10; factors['btts'].append(f"🔁 H2H обе забивали {h2h['btts_pct']}%")

    # ── Финальный расчёт вероятностей ─────────────────────
    total = scores['home_win'] + scores['draw'] + scores['away_win']
    if total <= 0: total = 100

    probs = {
        'home_win': round((scores['home_win'] / total) * 100, 1),
        'draw':     round((scores['draw'] / total) * 100, 1),
        'away_win': round((scores['away_win'] / total) * 100, 1),
    }
    over_base = 50 + scores['over_25'] * 0.3
    probs['over_25']   = round(min(85, max(15, over_base)), 1)
    probs['under_25']  = round(100 - probs['over_25'], 1)
    btts_base = 50 + scores['btts'] * 0.3
    probs['btts_yes']  = round(min(85, max(15, btts_base)), 1)
    probs['btts_no']   = round(100 - probs['btts_yes'], 1)

    # ── ML (80% вес) ──────────────────────────────────────
    ml = ml_predict(home, away, h2h, xg_data)
    blend = 0.80
    probs['home_win'] = round(probs['home_win'] * (1-blend) + ml['home_win'] * blend, 1)
    probs['away_win'] = round(probs['away_win'] * (1-blend) + ml['away_win'] * blend, 1)
    probs['draw']     = round(100 - probs['home_win'] - probs['away_win'], 1)
    probs['over_25']  = round(probs['over_25'] * (1-blend) + ml['over_25'] * blend, 1)
    probs['under_25'] = round(100 - probs['over_25'], 1)

    # ── V7.3: Адаптивная X ────────────────────────────────
    adaptive_draw = calculate_adaptive_draw_probability(
        match_classification, probs['draw'], home_pos, away_pos
    )

    # V7.4: Корректировка X от зоны вылета
    if relegation_ctx and relegation_ctx.get('flag'):
        adaptive_draw = min(45.0, adaptive_draw + relegation_ctx['draw_bonus'])

    # V7.4: Корректировка X от еврокубковой зоны (оба топ-7 = меньше X)
    if european_ctx:
        adaptive_draw = max(12.0, adaptive_draw - european_ctx['draw_penalty'])
        factors['over_25'].append(european_ctx['note'])

    # Применяем adaptive_draw
    draw_diff = adaptive_draw - probs['draw']
    total_p1_p2 = probs['home_win'] + probs['away_win']
    if total_p1_p2 > 0:
        hw_ratio = probs['home_win'] / total_p1_p2
        probs['home_win'] = round(probs['home_win'] - draw_diff * hw_ratio, 1)
        probs['away_win'] = round(probs['away_win'] - draw_diff * (1 - hw_ratio), 1)
    probs['draw'] = round(adaptive_draw, 1)

    # Нормализация
    total_norm = probs['home_win'] + probs['draw'] + probs['away_win']
    if total_norm != 100:
        diff = 100 - total_norm
        probs['home_win'] = round(probs['home_win'] + diff * 0.5, 1)
        probs['away_win'] = round(probs['away_win'] + diff * 0.5, 1)

    # ── V7.5: Тотал — лидер в гостях → ПОЛНЫЙ ЗАПРЕТ ТБ ─────
    if leader_away_ctx:
        if leader_away_ctx.get('block_over'):
            # V7.5: полный запрет ТБ при лидере в гостях
            probs['over_25']  = round(max(15, probs['over_25'] - leader_away_ctx['over_penalty']), 1)
            probs['under_25'] = round(100 - probs['over_25'], 1)
        else:
            probs['over_25']  = round(max(15, probs['over_25'] - leader_away_ctx['over_penalty']), 1)
            probs['under_25'] = round(100 - probs['over_25'], 1)
        factors['over_25'].append(leader_away_ctx['note'])

    # V7.4: Еврокубковая зона → ТБ бонус
    if european_ctx:
        probs['over_25']  = round(min(85, probs['over_25'] + european_ctx['over_bonus']), 1)
        probs['under_25'] = round(100 - probs['over_25'], 1)

    # Дерби → ТБ (+8%) и снижение ТБ при высокой X (V7.3)
    if match_class == 'DERBY':
        probs['over_25'] = round(min(probs['over_25'] + 8, 75), 1)
        probs['under_25'] = round(100 - probs['over_25'], 1)
    if probs['draw'] > 30 and not european_ctx:
        probs['over_25'] = round(max(probs['over_25'] - 5, 15), 1)
        probs['under_25'] = round(100 - probs['over_25'], 1)

    # ── V7.4: Уверенность (с зоной вылета) ───────────────
    conf = calculate_dynamic_confidence_v74(
        probs, factors, ml, match_classification, relegation_ctx
    )

    # ── Лучшая ставка ─────────────────────────────────────
    best = _find_best_bet_v74(probs, factors, odds, home, away,
                               match_classification, relegation_ctx, european_ctx,
                               leader_away_ctx)

    return {
        'probs': probs, 'confidence': conf,
        'best_bet': best, 'factors': factors,
        'xg_used': xg_data is not None,
        'odds_used': odds is not None,
        'h2h': h2h, 'ml': ml,
        'standings': standings,
        'home_congestion': home_congestion,
        'away_congestion': away_congestion,
        'match_classification': match_classification,
        'home_pos': home_pos, 'away_pos': away_pos,
        # V7.4 новые поля
        'relegation_ctx': relegation_ctx,
        'european_ctx': european_ctx,
        'leader_away_ctx': leader_away_ctx,
    }


def _find_best_bet_v74(probs, factors, odds, home, away, match_classification,
                        relegation_ctx=None, european_ctx=None, leader_away_ctx=None):
    """V7.4: Умный выбор ставки"""
    match_class = match_classification['match_class']
    recommendation = match_classification['recommendation']

    # Дерби и близкие команды → только X или ТБ
    if recommendation == 'SKIP':
        if probs['draw'] >= 35:
            return {
                'type': 'X (Ничья)', 'prob': probs['draw'],
                'odds': odds.get('draw') if odds else None,
                'value': 0, 'factors': factors.get('draw', []),
                'score': probs['draw'],
                'warning': match_classification['reason'],
            }
        if match_class == 'DERBY' and probs['over_25'] >= 60:
            return {
                'type': 'ТБ 2.5', 'prob': probs['over_25'],
                'odds': odds.get('over_25') if odds else None,
                'value': 0, 'factors': factors.get('over_25', []),
                'score': probs['over_25'],
                'warning': '⚠️ Дерби — рекомендуется ТБ, не П1/П2',
            }
        return {'type': None, 'prob': 0, 'warning': match_classification['reason']}

    candidates = []
    min_outcome_prob = 55 if match_class == 'MEDIUM_FAVORITE' else 42

    # V7.4: Зона вылета → повышаем порог для П1/П2
    if relegation_ctx and relegation_ctx.get('flag'):
        min_outcome_prob = max(min_outcome_prob, 55)

    for key, label, odds_key in [
        ('home_win', f"П1 {home['name']}", 'home_win'),
        ('away_win', f"П2 {away['name']}", 'away_win'),
        ('draw', 'Ничья', 'draw'),
    ]:
        if probs[key] >= min_outcome_prob:
            value = 0
            odds_val = None
            if odds and odds.get(odds_key):
                mp = odds_to_prob(odds[odds_key])
                value = probs[key] - mp
                odds_val = odds[odds_key]
            candidates.append({
                'type': label, 'prob': probs[key], 'odds': odds_val,
                'value': value, 'factors': factors.get(key, []),
                'score': probs[key] + max(0, value) * 2,
                'warning': relegation_ctx['warning'] if relegation_ctx and relegation_ctx.get('flag') else None,
            })

    # V7.5: ПОЛНЫЙ ЗАПРЕТ ТБ если лидер в гостях (1-2 место)
    leader_blocks_over = leader_away_ctx and leader_away_ctx.get('block_over', False)

    # V7.4: СТРОГИЙ ПОРОГ ТБ = 65% (было 58-62%)
    # Исключение: еврокубковая зона → 60%
    tb_threshold = 60 if european_ctx else 65

    if probs['over_25'] >= tb_threshold and not leader_blocks_over:
        candidates.append({
            'type': 'ТБ 2.5', 'prob': probs['over_25'],
            'odds': odds.get('over_25') if odds else None,
            'value': 0, 'factors': factors.get('over_25', []),
            'score': probs['over_25'],
            'warning': None,
        })

    if probs['btts_yes'] >= 65:
        candidates.append({
            'type': 'Обе забьют (Да)', 'prob': probs['btts_yes'],
            'odds': odds.get('btts_yes') if odds else None,
            'value': 0, 'factors': factors.get('btts', []),
            'score': probs['btts_yes'],
            'warning': None,
        })

    if not candidates:
        return {'type': None, 'prob': 0,
                'warning': f"Нет чёткого сигнала ({match_classification['reason']})"}
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[0]


# ============ ФОРМАТИРОВАНИЕ V7.4 ============

def format_result_v74(match, home, away, analysis):
    """V7.5: Вывод с поддержкой режима еврокубков"""
    best = analysis['best_bet']
    probs = analysis['probs']
    conf = analysis['confidence']
    mc = analysis['match_classification']
    match_class = mc['match_class']
    home_pos = analysis.get('home_pos')
    away_pos = analysis.get('away_pos')
    rel_ctx  = analysis.get('relegation_ctx')
    eur_ctx  = analysis.get('european_ctx')
    lea_ctx  = analysis.get('leader_away_ctx')
    is_euro  = analysis.get('is_euro_cup', False)

    dt = datetime.fromisoformat(match['date'].replace('Z', '+00:00'))
    conf_icon = "🟢" if conf >= 75 else "🟡" if conf >= 60 else "🔴"

    lines = []
    lines.append(f"⚽ *{home['name']}* vs *{away['name']}*")
    lines.append(f"📅 {dt.strftime('%d.%m.%Y %H:%M')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # V7.5: Специальный заголовок для еврокубков
    if is_euro:
        lines.append("🏆 *ЛИГА ЧЕМПИОНОВ / ЕВРОКУБОК*")
        lines.append("_Анализ без учёта таблицы нацчемпионата_")
        if mc.get('is_derby'):
            lines.append("🔥 *ДЕРБИ!*")
    else:
        type_labels = {
            'CLEAR_FAVORITE': f"✅ *Явный фаворит* (разница {mc['gap']} позиций)",
            'MEDIUM_FAVORITE': f"⚠️ *Средний фаворит* (разница {mc['gap']} позиций)",
            'CLOSE': "🚨 *Близкие команды* — высокая вероятность ничьи",
            'DERBY': "🔥 *ДЕРБИ!* Высокая непредсказуемость",
        }
        lines.append(type_labels.get(match_class, ''))

        if rel_ctx and rel_ctx.get('flag'):
            lines.append(f"_{rel_ctx['warning']}_")
        if eur_ctx:
            lines.append("_🇪🇺 Оба в еврокубковой зоне — атакующий матч_")
        if lea_ctx:
            lines.append(f"_{lea_ctx['note']}_")
        if match_class in ('CLOSE', 'DERBY'):
            lines.append(f"_X = {probs['draw']}% (реально ~35-45%)_")

    lines.append("")

    # Главная рекомендация
    if best and best.get('type'):
        odds_str = f" @ `{best['odds']}`" if best.get('odds') else ""
        value_str = f"\n💎 VALUE +{best['value']:.1f}% vs рынок" if best.get('value', 0) > 5 else ""
        warning_str = f"\n⚠️ _{best['warning']}_" if best.get('warning') else ""
        lines.append(f"🎯 *СТАВИТЬ: {best['type']}{odds_str}*{value_str}{warning_str}")
        lines.append(f"{conf_icon} Уверенность: *{conf}%*")
        lines.append("")
        top_factors = (best.get('factors') or [])[:4]
        if top_factors:
            lines.append("*Факторы:*")
            for f in top_factors:
                lines.append(f"  {f}")
    else:
        warning = (best or {}).get('warning', 'Нет чёткого сигнала')
        lines.append("🚫 *ПРОПУСТИТЬ МАТЧ*")
        lines.append(f"_{warning}_")
        lines.append(f"{conf_icon} Уверенность: *{conf}%*")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    lines.append("*📊 ИСХОД:*")
    lines.append(f"П1: *{probs['home_win']}%* | X: *{probs['draw']}%* | П2: *{probs['away_win']}%*")
    lines.append("")

    over = probs['over_25']
    under = probs['under_25']
    lines.append("*⚽ ТОТАЛ ГОЛОВ (2.5):*")
    lines.append(f"{'✅' if over >= 65 else '⬜'} ТБ 2.5: *{over}%*  |  {'✅' if under >= 65 else '⬜'} ТМ 2.5: *{under}%*")
    lines.append("")

    btts_yes = probs['btts_yes']
    btts_no = probs['btts_no']
    lines.append("*🥅 ОБЕЗАБЬЮТ:*")
    lines.append(f"{'✅' if btts_yes >= 65 else '⬜'} Да: *{btts_yes}%*  |  {'✅' if btts_no >= 65 else '⬜'} Нет: *{btts_no}%*")
    lines.append("")

    h2h = analysis.get('h2h')
    if h2h and h2h['total'] >= 2:
        lines.append(f"*🔁 H2H (последние {h2h['total']} встречи):*")
        lines.append(f"П1: {h2h['home_wins']} | Н: {h2h['draws']} | П2: {h2h['away_wins']}  _⚽ {h2h['avg_goals']}/матч_")
        lines.append("")

    if home_pos and away_pos and not is_euro:
        home_ctx = analyze_table_context(home_pos)
        away_ctx = analyze_table_context(away_pos)
        lines.append(f"*📊 ТАБЛИЦА:* {home['name']}: {home_pos} место | {away['name']}: {away_pos} место")
        contexts = []
        if home_ctx['context'] != 'Середина таблицы':
            contexts.append(f"{home['name']}: {home_ctx['description']}")
        if away_ctx['context'] != 'Середина таблицы':
            contexts.append(f"{away['name']}: {away_ctx['description']}")
        if contexts:
            lines.append(f"_{'| '.join(contexts)}_")
        lines.append("")

    home_cong = analysis.get('home_congestion')
    away_cong = analysis.get('away_congestion')
    fatigue_notes = []
    if home_cong and home_cong['fatigue_factor'] >= 2:
        fatigue_notes.append(f"😴 {home['name']}: отдых {home_cong['days_rest']}д")
    if away_cong and away_cong['fatigue_factor'] >= 2:
        fatigue_notes.append(f"😴 {away['name']}: отдых {away_cong['days_rest']}д")
    if fatigue_notes:
        lines.append("*⚠️ УСТАЛОСТЬ:*")
        for note in fatigue_notes: lines.append(f"  {note}")
        lines.append("")

    ml = analysis.get('ml')
    if ml:
        lines.append(f"*🤖 ML прогноз:* П1: {ml['home_win']}% | X: {ml['draw']}% | П2: {ml['away_win']}%")
        lines.append("")

    sources = ["📡 FD"]
    if analysis['xg_used']: sources.append("📈 xG")
    if analysis['odds_used']: sources.append("💰 Odds")
    if h2h: sources.append("🔁 H2H")
    if home_pos and not is_euro: sources.append("📊 Таблица")
    if ml: sources.append("🤖 ML")
    if is_euro: sources.append("🏆 ЛЧ-режим")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Анализ: {', '.join(sources)}_")
    lines.append("⚠️ _Ставьте ответственно!_")

    return "\n".join(lines)
    best = analysis['best_bet']
    probs = analysis['probs']
    conf = analysis['confidence']
    mc = analysis['match_classification']
    match_class = mc['match_class']
    home_pos = analysis.get('home_pos')
    away_pos = analysis.get('away_pos')
    rel_ctx  = analysis.get('relegation_ctx')
    eur_ctx  = analysis.get('european_ctx')
    lea_ctx  = analysis.get('leader_away_ctx')

    dt = datetime.fromisoformat(match['date'].replace('Z', '+00:00'))
    conf_icon = "🟢" if conf >= 75 else "🟡" if conf >= 60 else "🔴"

    lines = []
    lines.append(f"⚽ *{home['name']}* vs *{away['name']}*")
    lines.append(f"📅 {dt.strftime('%d.%m.%Y %H:%M')}")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # Тип матча
    type_labels = {
        'CLEAR_FAVORITE': f"✅ *Явный фаворит* (разница {mc['gap']} позиций)",
        'MEDIUM_FAVORITE': f"⚠️ *Средний фаворит* (разница {mc['gap']} позиций)",
        'CLOSE': f"🚨 *Близкие команды* — высокая вероятность ничьи",
        'DERBY': f"🔥 *ДЕРБИ!* Высокая непредсказуемость",
    }
    lines.append(type_labels.get(match_class, ''))

    # V7.4: Дополнительные контексты
    if rel_ctx and rel_ctx.get('flag'):
        lines.append(f"_{rel_ctx['warning']}_")
    if eur_ctx:
        lines.append(f"_🇪🇺 Оба в еврокубковой зоне — атакующий матч_")
    if lea_ctx:
        lines.append(f"_{lea_ctx['note']}_")

    if match_class in ('CLOSE', 'DERBY'):
        lines.append(f"_X = {probs['draw']}% (реально ~35-45%)_")

    lines.append("")

    # Главная рекомендация
    if best and best.get('type'):
        odds_str = f" @ `{best['odds']}`" if best.get('odds') else ""
        value_str = f"\n💎 VALUE +{best['value']:.1f}% vs рынок" if best.get('value', 0) > 5 else ""
        warning_str = f"\n⚠️ _{best['warning']}_" if best.get('warning') else ""
        lines.append(f"🎯 *СТАВИТЬ: {best['type']}{odds_str}*{value_str}{warning_str}")
        lines.append(f"{conf_icon} Уверенность: *{conf}%*")
        lines.append("")
        top_factors = (best.get('factors') or [])[:4]
        if top_factors:
            lines.append("*Факторы:*")
            for f in top_factors:
                lines.append(f"  {f}")
    else:
        warning = (best or {}).get('warning', 'Нет чёткого сигнала')
        lines.append(f"🚫 *ПРОПУСТИТЬ МАТЧ*")
        lines.append(f"_{warning}_")
        lines.append(f"{conf_icon} Уверенность: *{conf}%*")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")

    # Исход
    lines.append("*📊 ИСХОД:*")
    lines.append(f"П1: *{probs['home_win']}%* | X: *{probs['draw']}%* | П2: *{probs['away_win']}%*")
    lines.append("")

    # Тотал
    over = probs['over_25']
    under = probs['under_25']
    lines.append("*⚽ ТОТАЛ ГОЛОВ (2.5):*")
    lines.append(f"{'✅' if over >= 65 else '⬜'} ТБ 2.5: *{over}%*  |  {'✅' if under >= 65 else '⬜'} ТМ 2.5: *{under}%*")
    lines.append("")

    # BTTS
    btts_yes = probs['btts_yes']
    btts_no = probs['btts_no']
    lines.append("*🥅 ОБЕЗАБЬЮТ:*")
    lines.append(f"{'✅' if btts_yes >= 65 else '⬜'} Да: *{btts_yes}%*  |  {'✅' if btts_no >= 65 else '⬜'} Нет: *{btts_no}%*")
    lines.append("")

    # H2H
    h2h = analysis.get('h2h')
    if h2h and h2h['total'] >= 3:
        lines.append(f"*🔁 H2H (последние {h2h['total']} встречи):*")
        lines.append(f"П1: {h2h['home_wins']} | Н: {h2h['draws']} | П2: {h2h['away_wins']}  _⚽ {h2h['avg_goals']}/матч_")
        lines.append("")

    # Таблица
    if home_pos and away_pos:
        home_ctx = analyze_table_context(home_pos)
        away_ctx = analyze_table_context(away_pos)
        lines.append(f"*📊 ТАБЛИЦА:* {home['name']}: {home_pos} место | {away['name']}: {away_pos} место")
        contexts = []
        if home_ctx['context'] != 'Середина таблицы':
            contexts.append(f"{home['name']}: {home_ctx['description']}")
        if away_ctx['context'] != 'Середина таблицы':
            contexts.append(f"{away['name']}: {away_ctx['description']}")
        if contexts:
            lines.append(f"_{'| '.join(contexts)}_")
        lines.append("")

    # Усталость
    home_cong = analysis.get('home_congestion')
    away_cong = analysis.get('away_congestion')
    fatigue_notes = []
    if home_cong and home_cong['fatigue_factor'] >= 2:
        fatigue_notes.append(f"😴 {home['name']}: отдых {home_cong['days_rest']}д")
    if away_cong and away_cong['fatigue_factor'] >= 2:
        fatigue_notes.append(f"😴 {away['name']}: отдых {away_cong['days_rest']}д")
    if fatigue_notes:
        lines.append("*⚠️ УСТАЛОСТЬ:*")
        for note in fatigue_notes: lines.append(f"  {note}")
        lines.append("")

    # ML
    ml = analysis.get('ml')
    if ml:
        lines.append(f"*🤖 ML прогноз:* П1: {ml['home_win']}% | X: {ml['draw']}% | П2: {ml['away_win']}%")
        lines.append("")

    # Источники
    sources = ["📡 FD"]
    if analysis['xg_used']: sources.append("📈 xG")
    if analysis['odds_used']: sources.append("💰 Odds")
    if h2h: sources.append("🔁 H2H")
    if home_pos: sources.append("📊 Таблица")
    if ml: sources.append("🤖 ML")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Анализ: {', '.join(sources)}_")
    lines.append("⚠️ _Ставьте ответственно!_")

    return "\n".join(lines)


# ============ TELEGRAM БОТ ============

class FootballBot:
    def __init__(self):
        self.user_data = {}

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        uid  = user.id

        # ── Проверка авторизации ───────────────────────────
        if not is_authorized(uid):
            # Уведомляем администратора о запросе
            if ADMIN_ID:
                keyboard = [
                    [
                        InlineKeyboardButton(
                            f"✅ Одобрить {user.first_name}",
                            callback_data=f"auth_approve_{uid}"
                        ),
                        InlineKeyboardButton(
                            "❌ Отклонить",
                            callback_data=f"auth_deny_{uid}"
                        ),
                    ]
                ]
                username_str = f"@{user.username}" if user.username else "нет username"
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"🔔 *Новый запрос доступа*\n\n"
                        f"👤 Имя: {user.full_name}\n"
                        f"🆔 ID: `{uid}`\n"
                        f"📛 Username: {username_str}\n\n"
                        f"Одобрить доступ?"
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            # Сообщаем пользователю что запрос отправлен
            await update.message.reply_text(
                "⏳ *Запрос доступа отправлен.*\n\n"
                "Ожидайте подтверждения от администратора. "
                "Обычно это занимает несколько минут.",
                parse_mode='Markdown'
            )
            return

        # ── Авторизован — показываем бота ─────────────────
        text = (
            f"⚽ *Привет, {user.first_name}!*\n\n"
            f"*Football Analyzer V7.6*\n"
            f"_Fallback классификация | Зона вылета fix | ЛЧ порог_\n\n"
            f"*Что нового vs V7.5:*\n"
            f"🔧 Fallback если нет таблицы (по коэф/ML)\n"
            f"⚽ Зона вылета гостей перебивает CLOSE\n"
            f"🏆 ЛЧ порог ТБ снижен 68%→65%\n\n"
            f"Выберите лигу и матч! 👇"
        )
        keyboard = [[InlineKeyboardButton("⚽ Выбрать лигу", callback_data="select_league")]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard),
                                         parse_mode='Markdown')

    async def select_league(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not is_authorized(query.from_user.id):
            await query.answer("⛔ Нет доступа", show_alert=True)
            return
        keyboard = [[InlineKeyboardButton(f"⚽ {n}", callback_data=f"lg_{n}")] for n in LEAGUES]
        await query.edit_message_text("🏆 *Выберите лигу:*",
                                       reply_markup=InlineKeyboardMarkup(keyboard),
                                       parse_mode='Markdown')

    async def show_matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not is_authorized(query.from_user.id):
            await query.answer("⛔ Нет доступа", show_alert=True)
            return
        league_name = query.data[3:]
        code = LEAGUES[league_name]
        await query.edit_message_text(f"⏳ Загружаю {league_name}...")

        data = fd_request(f'competitions/{code}/matches', {'status': 'SCHEDULED'})
        if not data or 'matches' not in data:
            await query.edit_message_text(
                "❌ Матчи не найдены",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Назад", callback_data="select_league")]]))
            return

        now = datetime.now(timezone.utc)
        upcoming = []
        for m in data['matches']:
            dt = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
            if now < dt < now + timedelta(days=7):
                upcoming.append({
                    'home': m['homeTeam']['name'], 'away': m['awayTeam']['name'],
                    'date': m['utcDate'],
                    'home_id': m['homeTeam']['id'], 'away_id': m['awayTeam']['id'],
                })

        upcoming = upcoming[:10]
        if not upcoming:
            await query.edit_message_text(
                "❌ Нет матчей на неделю",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Назад", callback_data="select_league")]]))
            return

        uid = query.from_user.id
        self.user_data[uid] = {'league': league_name, 'code': code, 'matches': upcoming}

        msg = f"🏆 *{league_name}*\n\n"
        keyboard = []
        for i, m in enumerate(upcoming, 1):
            dt = datetime.fromisoformat(m['date'].replace('Z', '+00:00'))
            derby_icon = "🔥 " if is_derby(m['home'], m['away']) else ""
            msg += f"{i}. {derby_icon}{m['home']} vs {m['away']}  _{dt.strftime('%d.%m %H:%M')}_\n"
            keyboard.append([InlineKeyboardButton(
                f"{i}. {derby_icon}{m['home']} vs {m['away']}", callback_data=f"mt_{i-1}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="select_league")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard),
                                       parse_mode='Markdown')

    async def analyze_match(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not is_authorized(query.from_user.id):
            await query.answer("⛔ Нет доступа", show_alert=True)
            return
        idx = int(query.data[3:])
        uid = query.from_user.id

        if uid not in self.user_data:
            await query.edit_message_text("❌ Нажмите /start")
            return

        m = self.user_data[uid]['matches'][idx]
        code = self.user_data[uid]['code']
        league = self.user_data[uid]['league']

        await query.edit_message_text(
            f"🔍 *Анализирую матч...*\n\n"
            f"*{m['home']}* vs *{m['away']}*\n\n"
            f"{'🏆 Режим Лиги Чемпионов...' if code in EURO_CUP_LEAGUES else '📊 Статистика...'}\n"
            f"💰 Коэффициенты...\n📈 xG...\n"
            f"🔁 H2H...\n🤖 ML...",
            parse_mode='Markdown'
        )

        # V7.6: Каждый запрос обёрнут в try/except
        # Если один зависает — пропускаем и идём дальше, не висим вечно
        try:
            home_stats = get_team_stats(m['home_id'], m['home'])
        except Exception as e:
            logger.warning(f"home_stats error: {e}")
            home_stats = _default_stats(m['home'])
        home_stats['id'] = m['home_id']

        try:
            away_stats = get_team_stats(m['away_id'], m['away'])
        except Exception as e:
            logger.warning(f"away_stats error: {e}")
            away_stats = _default_stats(m['away'])
        away_stats['id'] = m['away_id']

        try:
            odds = get_odds(code, m['home'], m['away'])
        except Exception as e:
            logger.warning(f"odds error: {e}")
            odds = None

        # xG — самый частый источник зависания (scraping Understat)
        # Даём только 8 секунд, потом None
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            xg_data = await asyncio.wait_for(
                loop.run_in_executor(None, get_xg_data, code, m['home'], m['away']),
                timeout=8.0
            )
        except Exception as e:
            logger.warning(f"xG timeout/error (пропускаем): {e}")
            xg_data = None

        try:
            h2h = get_h2h(m['home_id'], m['away_id'])
        except Exception as e:
            logger.warning(f"h2h error: {e}")
            h2h = None

        try:
            standings = get_standings(code)
        except Exception as e:
            logger.warning(f"standings error: {e}")
            standings = None

        try:
            home_congestion = check_fixture_congestion(m['home_id'])
        except Exception as e:
            logger.warning(f"home_congestion error: {e}")
            home_congestion = None

        try:
            away_congestion = check_fixture_congestion(m['away_id'])
        except Exception as e:
            logger.warning(f"away_congestion error: {e}")
            away_congestion = None

        try:
            analysis = mega_analysis_v74(
                home_stats, away_stats, odds, xg_data, code,
                h2h=h2h, standings=standings,
                home_congestion=home_congestion,
                away_congestion=away_congestion
            )
            result = format_result_v74(m, home_stats, away_stats, analysis)
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            result = (
                f"⚽ *{m['home']}* vs *{m['away']}*\n\n"
                f"❌ Ошибка анализа: {str(e)[:100]}\n\n"
                f"_Попробуйте ещё раз или выберите другой матч_"
            )

        keyboard = [
            [InlineKeyboardButton("🔙 К матчам", callback_data=f"lg_{league}")],
            [InlineKeyboardButton("🏠 Начало", callback_data="start_cmd")],
        ]
        try:
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard),
                                           parse_mode='Markdown')
        except Exception as e:
            # Если текст слишком длинный или Markdown ошибка
            logger.warning(f"Message send error: {e}")
            await query.edit_message_text(
                result[:4000],
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )


async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    bot = context.bot_data['bot']
    uid = query.from_user.id

    # ── Команды администратора (одобрение/отклонение) ─────
    if data.startswith('auth_approve_'):
        if uid != ADMIN_ID:
            await query.answer("⛔ Только для администратора", show_alert=True)
            return
        target_id = int(data.split('_')[2])
        authorize_user(target_id)
        await query.edit_message_text(
            f"✅ Пользователь `{target_id}` *одобрен* и получил доступ к боту.",
            parse_mode='Markdown'
        )
        # Уведомляем пользователя что доступ открыт
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="✅ *Доступ подтверждён!*\n\nНажмите /start чтобы начать.",
                parse_mode='Markdown'
            )
        except:
            pass
        return

    if data.startswith('auth_deny_'):
        if uid != ADMIN_ID:
            await query.answer("⛔ Только для администратора", show_alert=True)
            return
        target_id = int(data.split('_')[2])
        await query.edit_message_text(
            f"❌ Пользователь `{target_id}` *отклонён*.",
            parse_mode='Markdown'
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ Запрос на доступ отклонён.",
            )
        except:
            pass
        return

    # ── Обычные команды бота ──────────────────────────────
    if data in ('start_cmd', 'start'): await bot.start(update, context)
    elif data == 'select_league': await bot.select_league(update, context)
    elif data.startswith('lg_'): await bot.show_matches(update, context)
    elif data.startswith('mt_'): await bot.analyze_match(update, context)


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /users — список авторизованных (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа")
        return
    if not AUTHORIZED_USERS:
        await update.message.reply_text("📋 Список авторизованных пользователей пуст.")
        return
    text = f"📋 *Авторизованные пользователи ({len(AUTHORIZED_USERS)}):*\n\n"
    for uid in AUTHORIZED_USERS:
        text += f"• `{uid}`\n"
    text += "\n_/revoke [user_id] — убрать доступ_"
    await update.message.reply_text(text, parse_mode='Markdown')


async def admin_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /revoke [user_id] — убрать доступ"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа")
        return
    if not context.args:
        await update.message.reply_text("Использование: /revoke [user_id]")
        return
    try:
        target_id = int(context.args[0])
        revoke_user(target_id)
        await update.message.reply_text(f"✅ Доступ пользователя `{target_id}` отозван.",
                                         parse_mode='Markdown')
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="⚠️ Ваш доступ к Football Analyzer был отозван."
            )
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Неверный user_id")


def main():
    errors = []
    if not TELEGRAM_BOT_TOKEN: errors.append("❌ TELEGRAM_BOT_TOKEN")
    if not FOOTBALLDATA_API_KEY: errors.append("❌ FOOTBALLDATA_API_KEY")
    if errors:
        print("⚠️ ОШИБКИ:\n" + '\n'.join(errors))
        return

    print("=" * 60)
    print("🤖 FOOTBALL ANALYZER V7.6")
    print("=" * 60)
    print("✅ Конфигурация проверена!")
    print(f"💰 Odds API: {'✅' if ODDS_API_KEY else '⚠️'}")
    print("")
    print("🆕 ИЗМЕНЕНИЯ V7.6 vs V7.5:")
    print("  🔧 Fallback классификация (standings=None)")
    print("     • Marseille(3) vs Auxerre(16) давал gap=0 → X. ИСПРАВЛЕНО!")
    print("     • Теперь: П1@1.42 → автоматически CLEAR_FAVORITE")
    print("     • Приоритет: коэффициенты → ML → ПРОПУСТИТЬ")
    print("  ⚽ Зона вылета гостей перебивает CLOSE")
    print("     • Gladbach(12) vs St.Pauli(16): gap=4 → CLOSE → X")
    print("     • Реально: St.Pauli в зоне → П1 2:0")
    print("     • Теперь: CLOSE + гости в зоне → MEDIUM_FAVORITE")
    print("  🏆 ЛЧ порог ТБ: 68% → 65%")
    print("     • Real Madrid-ManCity: ТБ 67.9% не рекомендовал (3 гола!)")
    print("")
    print("📊 Статистика V7.5 (нацчемпионаты):")
    print("   • Исход: 43% ❌ (баг standings) | Тотал: 75% ✅")
    print("📊 Цель V7.6: Исход 60%+")
    print("=" * 60)
    print("🚀 Запускаю бота...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    fb = FootballBot()
    app.bot_data['bot'] = fb
    app.add_handler(CommandHandler("start", fb.start))
    app.add_handler(CommandHandler("users", admin_users))
    app.add_handler(CommandHandler("revoke", admin_revoke))
    app.add_handler(CallbackQueryHandler(handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
