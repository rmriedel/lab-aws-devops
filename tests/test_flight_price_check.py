"""Tests de la logica pura de flight_price_check - nada de esto llama a SerpApi ni a AWS."""
from datetime import date, datetime, timedelta, timezone


def _segment(dep_airport, dep_time, arr_airport, arr_time, airline="Aerolineas Argentinas", duration=90):
    return {
        "airline": airline,
        "flight_number": "AR 1234",
        "departure_airport": {"id": dep_airport, "time": dep_time},
        "arrival_airport": {"id": arr_airport, "time": arr_time},
        "duration": duration,
    }


def test_date_grid_respeta_ventana_y_paso(flight_price_check):
    dates = flight_price_check._date_grid(window_days=60, step_days=5)
    # offsets 1, 6, 11, ..., 56 -> 12 fechas
    assert len(dates) == 12
    assert all((b - a).days == 5 for a, b in zip(dates, dates[1:], strict=False))
    assert dates[0] == datetime.now(timezone.utc).date() + timedelta(days=1)


def test_cheapest_itinerary_ignora_items_sin_precio(flight_price_check):
    payload = {
        "best_flights": [{"price": 150000}, {"sin": "precio"}],
        "other_flights": [{"price": 90000}, {"price": 120000}],
    }
    assert flight_price_check._cheapest_itinerary(payload) == {"price": 90000}


def test_cheapest_itinerary_vacio_devuelve_none(flight_price_check):
    assert flight_price_check._cheapest_itinerary({}) is None
    assert flight_price_check._cheapest_itinerary({"best_flights": [{"sin": "precio"}]}) is None


def test_parse_leg_directo(flight_price_check):
    itinerary = {
        "flights": [_segment("MDZ", "2026-12-01 08:00", "BRC", "2026-12-01 09:30")],
        "total_duration": 90,
    }
    leg = flight_price_check._parse_leg(itinerary)
    assert leg["is_direct"] is True
    assert leg["stops"] == 0
    assert leg["layovers"] == []
    assert leg["self_transfer"] is False
    assert leg["segments"][0]["from"] == "MDZ"
    assert leg["segments"][0]["to"] == "BRC"


def test_parse_leg_con_escala(flight_price_check):
    itinerary = {
        "flights": [
            _segment("MDZ", "2026-12-01 08:00", "AEP", "2026-12-01 10:00"),
            _segment("AEP", "2026-12-01 16:00", "BRC", "2026-12-01 18:20"),
        ],
        "layovers": [{"id": "AEP", "duration": 360}],
        "total_duration": 620,
    }
    leg = flight_price_check._parse_leg(itinerary)
    assert leg["is_direct"] is False
    assert leg["stops"] == 1
    assert flight_price_check._total_layover_minutes(leg) == 360


def test_combine_self_transfer_leg(flight_price_check):
    it1 = {"flights": [_segment("MDZ", "2026-12-01 08:00", "AEP", "2026-12-01 10:00")], "total_duration": 120}
    it2 = {
        "flights": [_segment("AEP", "2026-12-01 12:00", "BRC", "2026-12-01 14:20", airline="JetSMART")],
        "total_duration": 140,
    }
    leg = flight_price_check._combine_self_transfer_leg(it1, it2, "AEP", 120.0)
    assert leg["self_transfer"] is True
    assert leg["stops"] == 1
    assert leg["layovers"] == [{"airport": "AEP", "duration_minutes": 120}]
    assert leg["duration_minutes"] == 120 + 120 + 140
    assert [s["airline"] for s in leg["segments"]] == ["Aerolineas Argentinas", "JetSMART"]


def test_maybe_improve_leg_no_busca_combos_si_es_directo(flight_price_check, monkeypatch):
    def _no_deberia_llamarse(*args, **kwargs):
        raise AssertionError("no deberia buscar combos para un tramo directo")

    monkeypatch.setattr(flight_price_check, "_best_self_transfer_combo", _no_deberia_llamarse)
    leg = {"is_direct": True, "layovers": []}
    assert flight_price_check._maybe_improve_leg(leg, 100, "MDZ", "BRC", date(2026, 12, 1), "k", [], "R", "ida") == (leg, 100)


def test_maybe_improve_leg_no_paga_de_mas_por_un_combo(flight_price_check, monkeypatch):
    leg = {"is_direct": False, "layovers": [{"airport": "AEP", "duration_minutes": 500}]}
    combo_leg = {"self_transfer": True}

    monkeypatch.setattr(flight_price_check, "_best_self_transfer_combo", lambda *a, **k: {"price": 120, "leg": combo_leg})
    assert flight_price_check._maybe_improve_leg(leg, 100, "MDZ", "BRC", date(2026, 12, 1), "k", [], "R", "ida") == (leg, 100)

    monkeypatch.setattr(flight_price_check, "_best_self_transfer_combo", lambda *a, **k: {"price": 100, "leg": combo_leg})
    assert flight_price_check._maybe_improve_leg(leg, 100, "MDZ", "BRC", date(2026, 12, 1), "k", [], "R", "ida") == (combo_leg, 100)


def test_best_self_transfer_combo_respeta_ventana_de_conexion(flight_price_check, monkeypatch):
    # MDZ->hub llega 10:00. hub->BRC sale 10:30 (conexion de 30min, muy corta),
    # 12:00 (2h, valida pero cara) o 13:00 (3h, valida y la mas barata).
    def fake_fetch(origin, destination, d, api_key):
        if destination in flight_price_check.HUBS:
            return {"best_flights": [{"price": 50, "flights": [_segment(origin, "2026-12-01 08:00", destination, "2026-12-01 10:00")]}]}
        return {
            "best_flights": [
                {"price": 10, "flights": [_segment(origin, "2026-12-01 10:30", destination, "2026-12-01 12:30")]},
                {"price": 80, "flights": [_segment(origin, "2026-12-01 12:00", destination, "2026-12-01 14:00")]},
                {"price": 60, "flights": [_segment(origin, "2026-12-01 13:00", destination, "2026-12-01 15:00")]},
            ]
        }

    monkeypatch.setattr(flight_price_check, "_fetch_one_way", fake_fetch)
    raw = []
    best = flight_price_check._best_self_transfer_combo("MDZ", "BRC", date(2026, 12, 1), "k", raw)
    assert best["price"] == 110  # 50 + 60, la de 30min de conexion se descarta aunque sea mas barata
    assert best["leg"]["layovers"][0]["duration_minutes"] == 180
    assert len(raw) == 2 * len(flight_price_check.HUBS)
