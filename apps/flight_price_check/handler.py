"""
Lambda periodico: para cada ruta activa en watched_routes, barre una grilla
de fechas de ida (grid fijo, no cada dia) contra la API de SerpApi
(motor google_flights, API oficial sobre Google Flights) y guarda en
flight_prices el mejor precio ida y vuelta encontrado en todo el rango, con el
detalle completo de vuelos/escalas de ambos tramos.

Una sola consulta a Google Flights ya trae ambas aerolineas (AR y JetSmart)
(confirmado en vivo el 25/08 contra MDZ-BRC).

Solo stdlib (urllib, json) + boto3 (ya viene en el runtime de Lambda) - sin
paso de build, igual que el resto de los Lambdas de este repo.

MODELO DE PRECIO (25/08, revisado el mismo dia): cada tramo (ida y vuelta) se
cotiza INDEPENDIENTE como one-way (type=2) y el total es la suma de los dos.
Se abandono el enfoque anterior de pedir el viaje "armado" con type=1
(round trip) + un call extra con departure_token para el detalle de vuelta:
ese precio bundleado no se puede descomponer por tramo, y por lo tanto no
se puede reemplazar un solo tramo por una combinacion de aerolineas sin
perder consistencia de precio. Con precios one-way independientes por tramo,
"directo" tambien deja de ser una aproximacion (antes solo se verificaba el
tramo de ida durante el barrido) - ahora es exacto para ambos tramos.

COMBINACION DE AEROLINEAS (self-transfer / virtual interlining): si el tramo
ganador del barrido no es directo y su escala real supera
LAYOVER_THRESHOLD_MINUTES, se buscan combinaciones de dos vuelos nonstop
distintos (de cualquier aerolinea) via cada hub de HUBS, con tiempo de
conexion entre MIN_CONNECTION_MINUTES y LAYOVER_THRESHOLD_MINUTES. Se
reemplaza el tramo oficial solo si el combo sale igual o mas barato - nunca
se paga de mas solo por acortar la espera. Esto SOLO se hace para la fecha
que ya gano el barrido con precios oficiales, no para las ~11 fechas
restantes del rango (multiplicaria el costo por poco beneficio real). Un
itinerario armado asi son dos tickets separados: si el primer vuelo se
demora, la segunda aerolinea no tiene obligacion de esperar ni reacomodar -
se marca "self_transfer" en el tramo para que el mail de alerta lo aclare.

CONFIRMADO CONTRA LA API REAL (25/08):
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

# Combinacion de aerolineas via Buenos Aires: umbral de escala que dispara la
# busqueda de combos, ventana de conexion aceptable, y que hubs probar.
LAYOVER_THRESHOLD_MINUTES = 240
MIN_CONNECTION_MINUTES = 60
HUBS = ["AEP", "EZE"]

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


def _fetch_one_way(origin, destination, date, api_key):
    return _serpapi_get(
        {
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": date.isoformat(),
            "type": "2",
        },
        api_key,
    )


def _cheapest_itinerary(payload):
    itineraries = [
        it for it in payload.get("best_flights", []) + payload.get("other_flights", []) if "price" in it
    ]
    return min(itineraries, key=lambda it: it["price"]) if itineraries else None


def _parse_dt(time_str):
    return datetime.strptime(time_str, "%Y-%m-%d %H:%M")


def _parse_leg(itinerary):
    """De un itinerario one-way de SerpApi, arma el detalle de un tramo:
    segmentos de vuelo (con horarios) y escalas (con su duracion)."""
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
        "self_transfer": False,
    }


def _total_layover_minutes(leg):
    return sum(lay["duration_minutes"] for lay in leg["layovers"])


def _combine_self_transfer_leg(itinerary1, itinerary2, hub, connection_minutes):
    leg1 = _parse_leg(itinerary1)
    leg2 = _parse_leg(itinerary2)
    return {
        "segments": leg1["segments"] + leg2["segments"],
        "layovers": [{"airport": hub, "duration_minutes": round(connection_minutes)}],
        "stops": 1,
        "is_direct": False,
        "duration_minutes": leg1["duration_minutes"] + round(connection_minutes) + leg2["duration_minutes"],
        "self_transfer": True,
    }


def _best_self_transfer_combo(origin, destination, date, api_key, raw_responses):
    """Busca combinar dos vuelos nonstop (de cualquier aerolinea) via AEP o
    EZE con una conexion razonable. Devuelve {"price": ..., "leg": ...} del
    combo mas barato encontrado, o None si no hubo ninguno dentro de la
    ventana de conexion aceptable."""
    best = None

    for hub in HUBS:
        try:
            leg1_payload = _fetch_one_way(origin, hub, date, api_key)
            leg2_payload = _fetch_one_way(hub, destination, date, api_key)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"    [combo via {hub}] error de red: {exc}")
            continue

        raw_responses.append({"self_transfer_hub": hub, "leg": 1, "response": leg1_payload})
        raw_responses.append({"self_transfer_hub": hub, "leg": 2, "response": leg2_payload})

        leg1_options = [
            it for it in leg1_payload.get("best_flights", []) + leg1_payload.get("other_flights", [])
            if "price" in it and len(it.get("flights", [])) == 1
        ]
        leg2_options = [
            it for it in leg2_payload.get("best_flights", []) + leg2_payload.get("other_flights", [])
            if "price" in it and len(it.get("flights", [])) == 1
        ]

        for it1 in leg1_options:
            arrival = _parse_dt(it1["flights"][0]["arrival_airport"]["time"])
            for it2 in leg2_options:
                departure = _parse_dt(it2["flights"][0]["departure_airport"]["time"])
                connection_minutes = (departure - arrival).total_seconds() / 60
                if not (MIN_CONNECTION_MINUTES <= connection_minutes <= LAYOVER_THRESHOLD_MINUTES):
                    continue
                price = it1["price"] + it2["price"]
                if best is None or price < best["price"]:
                    best = {
                        "price": price,
                        "leg": _combine_self_transfer_leg(it1, it2, hub, connection_minutes),
                    }

    return best


def _maybe_improve_leg(leg, leg_price, origin, destination, date, api_key, raw_responses, route_id, label):
    """Si el tramo no es directo y su escala es larga, busca un combo
    self-transfer mas barato o igual. Devuelve (leg_final, precio_final)."""
    if leg["is_direct"] or _total_layover_minutes(leg) <= LAYOVER_THRESHOLD_MINUTES:
        return leg, leg_price

    print(f"[{route_id}] {label}: escala de {_total_layover_minutes(leg)}min, buscando combos via {HUBS}")
    combo = _best_self_transfer_combo(origin, destination, date, api_key, raw_responses)
    if combo and combo["price"] <= leg_price:
        print(f"[{route_id}] {label}: combo encontrado a {combo['price']} {CURRENCY} (oficial: {leg_price})")
        return combo["leg"], combo["price"]

    return leg, leg_price


def _sweep_route(origin, destination, window_days, stay_nights, step_days, api_key, raw_responses):
    """
    Recorre la grilla de fechas para una ruta cotizando ida y vuelta como
    one-way independientes, y devuelve (mejor_directo_o_None,
    mejor_general_o_None) - cada uno un dict candidato o None. Cada respuesta
    cruda se va agregando a `raw_responses` (lista provista por el caller) a
    medida que llega, para poder subir a S3 lo que se haya conseguido incluso
    si el barrido se corta a mitad de camino. Un fallo en una fecha puntual
    no aborta el resto del barrido.
    """
    best_direct = None
    best_overall = None

    for outbound_date in _date_grid(window_days, step_days):
        return_date = outbound_date + timedelta(days=stay_nights)
        try:
            outbound_payload = _fetch_one_way(origin, destination, outbound_date, api_key)
            return_payload = _fetch_one_way(destination, origin, return_date, api_key)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"  [{outbound_date}] error de red: {exc}")
            continue

        raw_responses.append({"outbound_date": outbound_date.isoformat(), "leg": "outbound", "response": outbound_payload})
        raw_responses.append({"outbound_date": outbound_date.isoformat(), "leg": "return", "response": return_payload})

        outbound_it = _cheapest_itinerary(outbound_payload)
        return_it = _cheapest_itinerary(return_payload)
        if outbound_it is None or return_it is None:
            print(f"  [{outbound_date}] sin resultados en algun tramo")
            continue

        outbound_leg = _parse_leg(outbound_it)
        return_leg = _parse_leg(return_it)
        candidate = {
            "outbound_price": outbound_it["price"],
            "return_price": return_it["price"],
            "price": outbound_it["price"] + return_it["price"],
            "currency": CURRENCY,
            "outbound_date": outbound_date,
            "return_date": return_date,
            "outbound_leg": outbound_leg,
            "return_leg": return_leg,
            "is_direct": outbound_leg["is_direct"] and return_leg["is_direct"],
        }

        if best_overall is None or candidate["price"] < best_overall["price"]:
            best_overall = candidate
        if candidate["is_direct"] and (best_direct is None or candidate["price"] < best_direct["price"]):
            best_direct = candidate

    return best_direct, best_overall


def _build_item(route_id, scraped_at, origin, destination, price, airline, outbound_date, return_date, outbound_leg, return_leg):
    return {
        "route_id": route_id,
        "scraped_at": scraped_at,
        "origin": origin,
        "destination": destination,
        "airline": airline,
        "price": Decimal(str(price)),
        "currency": CURRENCY,
        "outbound_date": outbound_date.isoformat(),
        "return_date": return_date.isoformat(),
        "outbound": outbound_leg,
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

        outbound_leg, outbound_price = _maybe_improve_leg(
            winner["outbound_leg"], winner["outbound_price"], origin, destination,
            winner["outbound_date"], api_key, raw_responses, route_id, "ida",
        )
        return_leg, return_price = _maybe_improve_leg(
            winner["return_leg"], winner["return_price"], destination, origin,
            winner["return_date"], api_key, raw_responses, route_id, "vuelta",
        )
        total_price = outbound_price + return_price
        airlines = sorted({s["airline"] for s in outbound_leg["segments"] + return_leg["segments"]})

        if raw_responses:
            _upload_raw(raw_key, raw_responses, route_id)

        item = _build_item(
            route_id, scraped_at, origin, destination, total_price, " + ".join(airlines),
            winner["outbound_date"], winner["return_date"], outbound_leg, return_leg,
        )
        item["raw_s3_key"] = raw_key
        prices_table.put_item(Item=item)

        checked += 1
        stops_desc = "directo" if outbound_leg["is_direct"] else f"{outbound_leg['stops']} escala(s)"
        print(f"[{route_id}] mejor precio: {total_price} {CURRENCY} "
              f"({item['airline']}, ida {stops_desc}, "
              f"{winner['outbound_date']} -> {winner['return_date']})")

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
