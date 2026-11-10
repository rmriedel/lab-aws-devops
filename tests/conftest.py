"""
Fixtures compartidas. Los dos Lambdas se llaman handler.py, asi que se cargan
por path con nombres de modulo distintos en vez de `import handler` (si no,
el segundo import devolveria el primero desde sys.modules).

Ambos handlers leen os.environ y crean clientes boto3 al importarse: se
setean variables dummy + region para que eso no falle. Crear un cliente boto3
no hace ninguna llamada de red, y los tests nunca llaman a AWS de verdad
(los clientes que se usan se reemplazan con fakes via monkeypatch).
"""
import importlib.util
import os
from pathlib import Path

import pytest

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("WATCHED_ROUTES_TABLE", "test-watched-routes")
os.environ.setdefault("FLIGHT_PRICES_TABLE", "test-flight-prices")
os.environ.setdefault("RAW_BUCKET", "test-raw-bucket")
os.environ.setdefault("SERPAPI_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:000000000000:secret:test")
os.environ.setdefault("ALERT_FROM_EMAIL", "alertas@example.com")
os.environ.setdefault("ALERT_TO_EMAIL", "destino@example.com")


def _load(app_name):
    spec = importlib.util.spec_from_file_location(f"{app_name}_handler", APPS_DIR / app_name / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def flight_price_check():
    return _load("flight_price_check")


@pytest.fixture(scope="session")
def price_alert():
    return _load("price_alert")
