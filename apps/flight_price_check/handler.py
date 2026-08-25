"""
Lambda periodico: para cada ruta activa en watched_routes, barre una grilla
de fechas de ida (grid fijo, no cada dia) contra la API de SerpApi
(motor google_flights, API oficial sobre Google Flights) y guarda en flight_prices
el mejor precio ida y vuelta encontrado en todo el rango, con el detalle
completo de vuelos/escalas de ambos tramos.

Una sola consulta a Google Flights ya trae ambas aerolineas (AR y JetSmart)
(confirmado en vivo el 25/08 contra MDZ-BRC).

Solo stdlib (urllib, json) + boto3 (ya viene en el runtime de Lambda) - sin
paso de build, igual que el resto de los Lambdas de este repo.

CONFIRMADO CONTRA LA API REAL (25/08):
- Con type=1 (round trip), el campo "price" del itinerario en la PRIMERA
  respuesta ya es el total ida y vuelta. Para el BARRIDO (elegir la fecha mas
  barata) alcanza con esa primera llamada - no hace falta la segunda con
  departure_token solo para comparar precios.
- El campo "flights" de cada itinerario de esa primera llamada son los
  segmentos del tramo de IDA unicamente. "Directo" durante el barrido se
  aproxima como stops==0 en ese tramo.
- Una vez elegido el ganador del barrido, SI se hace una llamada extra con su
  `departure_token` para traer el detalle real del tramo de VUELTA (horarios,
  escalas y su duracion) - una sola llamada extra por ruta, no por cada fecha
  del barrido, para no multiplicar el costo.
- Algunos itinerarios vienen sin campo "price" - se descartan sin abortar
  el resto.
- price_insights.price_history es el historial de los ultimos ~60 dias de
  precio para ESE par de fechas puntual, no un calendario de fechas
  distintas - no sirve para "mejor precio en un rango", por eso barremos la
  grilla nosotros mismos con llamadas separadas.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

SERPAPI_URL = "https://serpapi.com/search.json"

# Dominio del proyecto es cabotaje argentino - se fijan estos tres a proposito
# en vez de leerlos por ruta.
CURRENCY = "ARS"
HL = "es"
GL = "ar"

# Defaults del barrido de fechas si la ruta no los especifica en watched_routes.
SEARCH_WINDOW_DAYS_DEFAULT = 60
STAY_NIGHTS_DEFAULT = 7
DATE_STEP_DAYS_DEFAULT = 5

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
secrets_client = boto3.client("secretsmanager")

WATCHED_ROUTES_TABLE = os.environ["WATCHED_ROUTES_TABLE"]
FLIGHT_PRICES_TABLE = os.environ["FLIGHT_PRICES_TABLE"]
RAW_BUCKET = os.environ["RAW_BUCKET"]
SERPAPI_SECRET_ARN = os.environ["SERPAPI_SECRET_ARN"]

# Cacheada a nivel de modulo: se reusa entre invocaciones del mismo entorno
# de ejecucion tibio, no hace falta pedirla a Secrets Manager en cada corrida.
_api_key_cache = None


def _get_api_key():
    global _api_key_cache
    if _api_key_cache is None:
        _api_key_cache = secrets_client.get_secret_value(SecretId=SERPAPI_SECRET_ARN)["SecretString"]
    return _api_key_cache


def _int_attr(route, name, default):
    return int(route.get(name, default))


def _date_grid(window_days, step_days):
    today = datetime.now(timezone.utc).date()
    dates = []
    offset = 1
    while offset <= window_days:
        dates.append(today + timedelta(days=offset))
        offset += step_days
    return dates


def _serpapi_get(extra_params, api_key):
    params = {
        "engine": "google_flights",
        "type": "1",
        "currency": CURRENCY,
        "hl": HL,
        "gl": GL,
        "api_key": api_key,
        **extra_params,
    }
    url = f"{SERPAPI_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw)


def _fetch_round_trip(origin, destination, outbound_date, return_date, api_key):
    return _serpapi_get(
        {
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": outbound_date.isoformat(),
            "return_date": return_date.isoformat(),
        },
        api_key,
    )


def _fetch_return_leg(origin, destination, outbound_date, return_date, departure_token, api_key):
    return _serpapi_get(
        {
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": outbound_date.isoformat(),
            "return_date": return_date.isoformat(),
            "departure_token": departure_token,
        },
        api_key,
    )


def _parse_leg(itinerary):
    """De un itinerario de SerpApi, arma el detalle de un tramo: segmentos
    de vuelo (con horarios) y escalas (con su duracion)."""
    segments = [
        {
            "airline": seg.get("airline", "?"),
            "flight_number": seg.get("flight_number", "?"),
            "from": seg.get("departure_airport", {}).get("id", "?"),
            "departure_time": seg.get("departure_airport", {}).get("time", "?"),
            "to": seg.get("arrival_airport", {}).get("id", "?"),
            "arrival_time": seg.get("arrival_airport", {}).get("time", "?"),
            "duration_minutes": seg.get("duration", 0),
        }
        for seg in itinerary.get("flights", [])
    ]
    layovers = [
        {
            "airport": lay.get("id") or lay.get("name", "?"),
            "duration_minutes": lay.get("duration", 0),
        }
        for lay in itinerary.get("layovers", [])
    ]
    return {
        "segments": segments,
        "layovers": layovers,
        "stops": max(len(segments) - 1, 0),
        "is_direct": len(segments) == 1,
        "duration_minutes": itinerary.get("total_duration", 0),
    }


def _itinerary_summary(itinerary, outbound_date, return_date):
    segments = itinerary.get("flights", [])
    airlines = sorted({s.get("airline", "?") for s in segments})
    return {
        "price": itinerary["price"],
        "currency": CURRENCY,
        "stops": max(len(segments) - 1, 0),
        "is_direct": len(segments) == 1,
        "airline": " + ".join(airlines) if airlines else "?",
        "outbound_date": outbound_date,
        "return_date": return_date,
        "departure_token": itinerary.get("departure_token"),
    }


def _sweep_route(origin, destination, window_days, stay_nights, step_days, api_key, raw_responses):
    """
    Recorre la grilla de fechas para una ruta y devuelve
    (mejor_directo_o_None, mejor_general_o_None), cada uno como una tupla
    (resumen, itinerario_crudo) o None. Cada respuesta cruda se va agregando
    a `raw_responses` (lista provista por el caller) a medida que llega, para
    poder subir a S3 lo que se haya conseguido incluso si el barrido se corta
    a mitad de camino por una excepcion inesperada. Un fallo en un par de
    fechas puntual no aborta el resto del barrido.
    """
    best_direct = None
    best_overall = None

    for outbound_date in _date_grid(window_days, step_days):
        return_date = outbound_date + timedelta(days=stay_nights)
        try:
            payload = _fetch_round_trip(origin, destination, outbound_date, return_date, api_key)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"  [{outbound_date}] error de red: {exc}")
            continue

        raw_responses.append({"outbound_date": outbound_date.isoformat(), "response": payload})

        if payload.get("error"):
            print(f"  [{outbound_date}] SerpApi devolvio error: {payload['error']}")
            continue

        itineraries = payload.get("best_flights", []) + payload.get("other_flights", [])
        for itinerary in itineraries:
            if "price" not in itinerary:
                continue
            summary = _itinerary_summary(itinerary, outbound_date, return_date)
            candidate = (summary, itinerary)

            if best_overall is None or summary["price"] < best_overall[0]["price"]:
                best_overall = candidate
            if summary["is_direct"] and (best_direct is None or summary["price"] < best_direct[0]["price"]):
                best_direct = candidate

    return best_direct, best_overall


def _build_item(route_id, scraped_at, origin, destination, summary, outbound_itinerary, return_leg, raw_key):
    return {
        "route_id": route_id,
        "scraped_at": scraped_at,
        "origin": origin,
        "destination": destination,
        "airline": summary["airline"],
        "price": Decimal(str(summary["price"])),
        "currency": summary["currency"],
        "outbound_date": summary["outbound_date"].isoformat(),
        "return_date": summary["return_date"].isoformat(),
        "outbound": _parse_leg(outbound_itinerary),
        "return": return_leg,
    }


def lambda_handler(event, context):
    routes_table = dynamodb.Table(WATCHED_ROUTES_TABLE)
    prices_table = dynamodb.Table(FLIGHT_PRICES_TABLE)

    routes = routes_table.scan(FilterExpression=Attr("active").eq(True)).get("Items", [])
    if not routes:
        print("No hay rutas activas en watched_routes")
        return {"checked": 0}

    api_key = _get_api_key()
    checked = 0

    for route in routes:
        route_id = route["route_id"]
        origin = route["origin"]
        destination = route["destination"]
        window_days = _int_attr(route, "search_window_days", SEARCH_WINDOW_DAYS_DEFAULT)
        stay_nights = _int_attr(route, "stay_nights", STAY_NIGHTS_DEFAULT)
        step_days = _int_attr(route, "date_step_days", DATE_STEP_DAYS_DEFAULT)
        scraped_at = datetime.now(timezone.utc).isoformat()
        raw_key = f"serpapi/{route_id}/{scraped_at}.json"

        print(f"[{route_id}] barriendo {origin}-{destination}, ventana={window_days}d, estadia={stay_nights}n, paso={step_days}d")

        raw_responses = []
        best_direct = best_overall = None
        try:
            best_direct, best_overall = _sweep_route(
                origin, destination, window_days, stay_nights, step_days, api_key, raw_responses
            )
        except Exception as exc:  # noqa: BLE001 - una ruta no debe tumbar el batch completo
            print(f"[{route_id}] error inesperado en el barrido: {exc}")

        winner = best_direct or best_overall
        if winner is None:
            print(f"[{route_id}] sin precios validos en toda la ventana")
            if raw_responses:
                _upload_raw(raw_key, raw_responses, route_id)
            continue

        winner_summary, winner_itinerary = winner

        # Un solo call extra (no por cada fecha del barrido) para traer el
        # detalle real del tramo de vuelta - horarios y escalas.
        return_leg = None
        if winner_summary["departure_token"]:
            try:
                return_payload = _fetch_return_leg(
                    origin, destination, winner_summary["outbound_date"], winner_summary["return_date"],
                    winner_summary["departure_token"], api_key,
                )
                raw_responses.append({"departure_token_followup": True, "response": return_payload})
                return_itineraries = [
                    it for it in return_payload.get("best_flights", []) + return_payload.get("other_flights", [])
                    if "price" in it
                ]
                if return_itineraries:
                    cheapest_return = min(return_itineraries, key=lambda it: it["price"])
                    return_leg = _parse_leg(cheapest_return)
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                print(f"[{route_id}] no se pudo obtener el detalle del tramo de vuelta: {exc}")

        if raw_responses:
            _upload_raw(raw_key, raw_responses, route_id)

        item = _build_item(route_id, scraped_at, origin, destination, winner_summary, winner_itinerary, return_leg, raw_key)
        item["raw_s3_key"] = raw_key
        prices_table.put_item(Item=item)

        checked += 1
        stops_desc = "directo" if item["outbound"]["is_direct"] else f"{item['outbound']['stops']} escala(s)"
        print(f"[{route_id}] mejor precio: {winner_summary['price']} {winner_summary['currency']} "
              f"({winner_summary['airline']}, ida {stops_desc}, "
              f"{winner_summary['outbound_date']} -> {winner_summary['return_date']})")

    return {"checked": checked}


def _upload_raw(raw_key, raw_responses, route_id):
    # Se sube siempre que haya algo que subir, exito o no, para poder
    # debuggear si SerpApi cambia de forma o empieza a fallar.
    try:
        s3.put_object(
            Bucket=RAW_BUCKET,
            Key=raw_key,
            Body=json.dumps(raw_responses, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[{route_id}] no se pudo subir el raw dump a S3: {exc}")
