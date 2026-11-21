"""Получение погоды для Петербурга. Только стандартная библиотека Python."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.request import Request, urlopen
import json
import math
import os
import threading
import time

MOSCOW = timezone(timedelta(hours=3))
OPEN_METEO_URL = (
    'https://api.open-meteo.com/v1/forecast?latitude=59.94&longitude=30.31'
    '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'
    '&forecast_days=16&timezone=Europe%2FMoscow'
)
MET_NO_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=59.94&lon=30.31'
SOURCES = {
    'open-meteo': {'id': 'open-meteo', 'name': 'Open-Meteo', 'url': 'https://open-meteo.com/'},
    'met-no': {'id': 'met-no', 'name': 'MET Norway', 'url': 'https://www.met.no/'},
}


class WeatherUnavailable(Exception):
    pass


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_json(url):
    # Идентификатор приложения, а не личные данные посетителя.
    user_agent = os.environ.get('WEATHER_USER_AGENT', 'UlitsaKoshachya/2.1')
    request = Request(url, headers={'User-Agent': user_agent, 'Accept': 'application/json'})
    with urlopen(request, timeout=6) as response:
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError('Слишком большой ответ погодного сервиса')
        data = json.loads(body)
        expires = response.headers.get('Expires')
    ttl = 600
    if expires:
        try:
            ttl = max(1, min(600, parsedate_to_datetime(expires).timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            pass
    return data, ttl


def validate_daily(daily):
    keys = ['weather_code', 'temperature_2m_min', 'temperature_2m_max',
            'precipitation_probability_max']
    dates = daily.get('time') if isinstance(daily, dict) else None
    if not isinstance(dates, list) or not dates:
        raise ValueError('Нет дат прогноза')
    for value in dates:
        if not isinstance(value, str) or datetime.strptime(value, '%Y-%m-%d').date().isoformat() != value:
            raise ValueError('Некорректная дата прогноза')
    if not all(isinstance(daily.get(key), list) and len(daily[key]) == len(dates) for key in keys):
        raise ValueError('Неполный ответ погодного сервиса')
    if not all(value is None or finite_number(value) for key in keys for value in daily[key]):
        raise ValueError('Некорректные числовые данные')
    if not any(finite_number(low) and finite_number(high) for low, high in
               zip(daily['temperature_2m_min'], daily['temperature_2m_max'])):
        raise ValueError('Нет температуры в прогнозе')
    return daily


def met_description(symbol):
    symbol = symbol.split('_')[0]
    exact = {'clearsky': 'Ясно', 'fair': 'Преимущественно ясно',
             'partlycloudy': 'Переменная облачность', 'cloudy': 'Пасмурно', 'fog': 'Туман'}
    if symbol in exact:
        return exact[symbol]
    if 'thunder' in symbol:
        return 'Гроза'
    if 'sleet' in symbol:
        return 'Мокрый снег'
    if 'snow' in symbol:
        return 'Снег'
    if 'rain' in symbol:
        return 'Дождь'
    return 'Описание погоды недоступно'


def normalize_met_no(data):
    if not isinstance(data, dict) or not isinstance(data.get('properties'), dict):
        raise ValueError('Некорректный ответ MET Norway')
    points = data['properties'].get('timeseries', [])
    if not isinstance(points, list):
        raise ValueError('Некорректный список сроков прогноза')
    grouped = {}
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get('time'), str) or not isinstance(point.get('data'), dict):
            raise ValueError('Некорректный срок прогноза')
        moment = datetime.fromisoformat(point['time'].replace('Z', '+00:00')).astimezone(MOSCOW)
        temperature = point.get('data', {}).get('instant', {}).get('details', {}).get('air_temperature')
        if not finite_number(temperature):
            continue
        grouped.setdefault(moment.date().isoformat(), []).append((moment, point, temperature))
    daily = {key: [] for key in ['time', 'weather_code', 'description', 'temperature_2m_min',
                                'temperature_2m_max', 'precipitation_probability_max']}
    for date, entries in sorted(grouped.items()):
        # Символ берём у ближайшего к полудню срока прогноза.
        _, representative, _ = min(entries, key=lambda entry: abs(entry[0].hour + entry[0].minute / 60 - 12))
        periods = representative.get('data', {})
        symbol = ''
        for period in ['next_1_hours', 'next_6_hours', 'next_12_hours']:
            symbol = periods.get(period, {}).get('summary', {}).get('symbol_code', '')
            if symbol:
                break
        temperatures = [entry[2] for entry in entries]
        daily['time'].append(date)
        daily['weather_code'].append(None)  # MET Norway использует собственные символьные коды.
        daily['description'].append(met_description(symbol))
        daily['temperature_2m_min'].append(min(temperatures))
        daily['temperature_2m_max'].append(max(temperatures))
        daily['precipitation_probability_max'].append(None)  # Не подменяем отсутствие данных нулём.
    return validate_daily(daily)


class WeatherService:
    def __init__(self, reader=read_json):
        self.reader = reader
        self.cached = None
        self.expires_at = 0
        self.lock = threading.Lock()

    def get_forecast(self):
        # Несколько одновременных открытий страницы используют один запрос.
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires_at:
                return self.cached
            providers = [('open-meteo', OPEN_METEO_URL), ('met-no', MET_NO_URL)]
            errors = []
            for provider, url in providers:
                try:
                    data, ttl = self.reader(url)
                    if not isinstance(data, dict):
                        raise ValueError('Ожидался JSON-объект')
                    if provider == 'open-meteo':
                        daily = validate_daily(data.get('daily'))
                    else:
                        daily = normalize_met_no(data)
                    result = {'daily': daily, 'source': SOURCES[provider],
                              'fetched_at': datetime.now(timezone.utc).isoformat()}
                    self.cached = result
                    self.expires_at = time.monotonic() + max(1, min(600, ttl))
                    return result
                except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as error:
                    errors.append(f'{provider}: {type(error).__name__}')
            raise WeatherUnavailable('; '.join(errors))
