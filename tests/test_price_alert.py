"""Tests de price_alert con DynamoDB y SES reemplazados por fakes en memoria."""
from decimal import Decimal

import pytest


class FakeTable:
    def __init__(self, items):
        self._items = items

    def get_item(self, Key):
        item = self._items.get(Key["route_id"])
        return {"Item": item} if item else {}


class FakeDynamo:
    def __init__(self, items):
        self._table = FakeTable(items)

    def Table(self, name):
        return self._table


class FakeSes:
    def __init__(self):
        self.sent = []

    def send_email(self, **kwargs):
        self.sent.append(kwargs)


def _stream_record(route_id, price, airline="Aerolineas Argentinas", self_transfer=False):
    leg = {
        "M": {
            "segments": {"L": [{"M": {"airline": {"S": airline}, "flight_number": {"S": "AR 1"}, "duration_minutes": {"N": "90"}}}]},
            "layovers": {"L": []},
            "self_transfer": {"BOOL": self_transfer},
        }
    }
    return {
        "dynamodb": {
            "NewImage": {
                "route_id": {"S": route_id},
                "origin": {"S": "MDZ"},
                "destination": {"S": "BRC"},
                "airline": {"S": airline},
                "price": {"N": str(price)},
                "currency": {"S": "ARS"},
                "outbound": leg,
                "return": leg,
            }
        }
    }


@pytest.fixture
def fakes(price_alert, monkeypatch):
    routes = {
        "MDZ-BRC": {"route_id": "MDZ-BRC", "target_price": Decimal("200000")},
        "MDZ-USH": {"route_id": "MDZ-USH", "target_price": Decimal("300000")},
    }
    ses = FakeSes()
    monkeypatch.setattr(price_alert, "dynamodb", FakeDynamo(routes))
    monkeypatch.setattr(price_alert, "ses", ses)
    return ses


def test_fmt_duration(price_alert):
    assert price_alert._fmt_duration(0) == "?"
    assert price_alert._fmt_duration(None) == "?"
    assert price_alert._fmt_duration(45) == "45m"
    assert price_alert._fmt_duration(135) == "2h 15m"


def test_no_manda_mail_si_ningun_precio_baja_del_objetivo(price_alert, fakes):
    result = price_alert.lambda_handler({"Records": [_stream_record("MDZ-BRC", 250000)]}, None)
    assert result == {"alerts_sent": 0}
    assert fakes.sent == []


def test_ignora_rutas_desconocidas_y_records_sin_imagen(price_alert, fakes):
    event = {"Records": [_stream_record("NO-EXISTE", 1), {"dynamodb": {}}]}
    assert price_alert.lambda_handler(event, None) == {"alerts_sent": 0}
    assert fakes.sent == []


def test_agrupa_varias_rutas_en_un_solo_mail(price_alert, fakes):
    event = {
        "Records": [
            _stream_record("MDZ-USH", 280000),
            _stream_record("MDZ-BRC", 150000),
            _stream_record("MDZ-BRC", 999999),  # sobre el objetivo, no entra
        ]
    }
    assert price_alert.lambda_handler(event, None) == {"alerts_sent": 2}
    assert len(fakes.sent) == 1

    mail = fakes.sent[0]
    assert mail["Source"] == "alertas@example.com"
    assert mail["Destination"] == {"ToAddresses": ["destino@example.com"]}
    assert mail["Message"]["Subject"]["Data"] == "Bajo de precio: 2 rutas"
    html = mail["Message"]["Body"]["Html"]["Data"]
    # Orden pedido: por ruta -> MDZ-BRC antes que MDZ-USH.
    assert html.index("MDZ-BRC") < html.index("MDZ-USH")


def test_avisa_tickets_separados(price_alert, fakes):
    price_alert.lambda_handler({"Records": [_stream_record("MDZ-BRC", 150000, self_transfer=True)]}, None)
    html = fakes.sent[0]["Message"]["Body"]["Html"]["Data"]
    assert fakes.sent[0]["Message"]["Subject"]["Data"] == "Bajo de precio: MDZ-BRC"
    assert "Tickets separados" in html
