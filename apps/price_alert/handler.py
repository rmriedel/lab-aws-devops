"""
Lambda disparado por el stream de flight_prices. Junta todas las rutas del
batch que bajaron de su target_price y manda UN solo mail HTML por SES con
todas juntas, en tabla, ordenadas por ruta / aerolinea / precio total - en
vez de un mail suelto (y en texto plano) por cada ruta.

SNS no soporta HTML en el cuerpo del mail (solo texto plano) - por eso SES en
vez de un topico SNS. Se manda de ALERT_EMAIL a ALERT_EMAIL (mismo valor en
los dos lados), asi alcanza con verificar una sola identidad en el sandbox de
SES, sin pedir salida de sandbox.
"""
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")
deserializer = TypeDeserializer()

WATCHED_ROUTES_TABLE = os.environ["WATCHED_ROUTES_TABLE"]
ALERT_EMAIL = os.environ["ALERT_EMAIL"]

TABLE_STYLE = (
    "border-collapse:collapse;width:100%;margin:8px 0 20px;font-family:sans-serif;font-size:14px;"
)
TH_STYLE = "text-align:left;border-bottom:2px solid #333;padding:4px 8px;"
TD_STYLE = "border-bottom:1px solid #ddd;padding:4px 8px;"
LAYOVER_STYLE = "padding:2px 8px;color:#666;font-style:italic;background:#f7f7f7;"


def _deserialize(dynamodb_json):
    return {k: deserializer.deserialize(v) for k, v in dynamodb_json.items()}


def _fmt_duration(minutes):
    minutes = int(minutes or 0)
    if minutes <= 0:
        return "?"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _leg_rows(label, leg):
    if not leg:
        return f"<tr><td style='{TD_STYLE}'>{label}</td><td colspan='6' style='{TD_STYLE}'><em>sin detalle</em></td></tr>"

    segments = leg.get("segments", [])
    layovers = leg.get("layovers", [])
    rows = []
    for i, seg in enumerate(segments):
        rows.append(
            f"<tr>"
            f"<td style='{TD_STYLE}'>{label if i == 0 else ''}</td>"
            f"<td style='{TD_STYLE}'>{seg.get('airline', '?')} {seg.get('flight_number', '')}</td>"
            f"<td style='{TD_STYLE}'>{seg.get('from', '?')}</td>"
            f"<td style='{TD_STYLE}'>{seg.get('departure_time', '?')}</td>"
            f"<td style='{TD_STYLE}'>{seg.get('to', '?')}</td>"
            f"<td style='{TD_STYLE}'>{seg.get('arrival_time', '?')}</td>"
            f"<td style='{TD_STYLE}'>{_fmt_duration(seg.get('duration_minutes'))}</td>"
            f"</tr>"
        )
        if i < len(layovers):
            lay = layovers[i]
            rows.append(
                f"<tr><td></td><td colspan='6' style='{LAYOVER_STYLE}'>"
                f"Escala en {lay.get('airport', '?')}: {_fmt_duration(lay.get('duration_minutes'))}"
                f"</td></tr>"
            )
    return "".join(rows)


def _route_section_html(item, target_price):
    currency = item.get("currency", "ARS")
    origin = item.get("origin", "?")
    destination = item.get("destination", "?")
    airline = item.get("airline", "?")

    rows = _leg_rows("Ida", item.get("outbound"))
    rows += _leg_rows("Vuelta", item.get("return"))

    return f"""
    <h2 style="margin:24px 0 4px;font-family:sans-serif;">{item['route_id']}: {origin} &rarr; {destination} &middot; {airline}</h2>
    <p style="font-family:sans-serif;margin:0 0 8px;">
      <strong>Total: {item['price']} {currency}</strong> (objetivo: {target_price} {currency})
    </p>
    <table style="{TABLE_STYLE}">
      <tr>
        <th style="{TH_STYLE}">Tramo</th><th style="{TH_STYLE}">Vuelo</th>
        <th style="{TH_STYLE}">Origen</th><th style="{TH_STYLE}">Salida</th>
        <th style="{TH_STYLE}">Destino</th><th style="{TH_STYLE}">Llegada</th>
        <th style="{TH_STYLE}">Duraci&oacute;n</th>
      </tr>
      {rows}
    </table>
    """


def lambda_handler(event, context):
    routes_table = dynamodb.Table(WATCHED_ROUTES_TABLE)
    alerts = []

    for record in event.get("Records", []):
        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue

        item = _deserialize(new_image)
        route = routes_table.get_item(Key={"route_id": item["route_id"]}).get("Item")
        if not route or "target_price" not in route:
            continue

        target_price = route["target_price"]
        if item["price"] < target_price:
            alerts.append((item, target_price))

    if not alerts:
        return {"alerts_sent": 0}

    # Orden pedido: ruta, aerolinea, precio total.
    alerts.sort(key=lambda pair: (pair[0]["route_id"], pair[0].get("airline", ""), pair[0]["price"]))

    subject = (
        f"Bajo de precio: {alerts[0][0]['route_id']}"
        if len(alerts) == 1
        else f"Bajo de precio: {len(alerts)} rutas"
    )
    sections = "".join(_route_section_html(item, target_price) for item, target_price in alerts)
    html_body = f"<html><body>{sections}</body></html>"

    ses.send_email(
        Source=ALERT_EMAIL,
        Destination={"ToAddresses": [ALERT_EMAIL]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
        },
    )

    return {"alerts_sent": len(alerts)}
