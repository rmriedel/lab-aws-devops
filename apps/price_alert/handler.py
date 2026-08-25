"""
Lambda disparado por el stream de flight_prices. Por cada precio nuevo,
compara contra el target_price de esa ruta en watched_routes y manda un
email por SNS si esta por debajo.
"""
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
deserializer = TypeDeserializer()

WATCHED_ROUTES_TABLE = os.environ["WATCHED_ROUTES_TABLE"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]


def _deserialize(dynamodb_json):
    return {k: deserializer.deserialize(v) for k, v in dynamodb_json.items()}


def lambda_handler(event, context):
    routes_table = dynamodb.Table(WATCHED_ROUTES_TABLE)
    alerts_sent = 0

    for record in event.get("Records", []):
        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue

        item = _deserialize(new_image)
        route_id = item["route_id"]
        price = item["price"]
        currency = item.get("currency", "ARS")
        airline = item.get("airline", "?")
        outbound_date = item.get("outbound_date")
        return_date = item.get("return_date")
        stops_desc = "directo" if item.get("is_direct") else f"{item.get('stops', '?')} escala(s)"

        route = routes_table.get_item(Key={"route_id": route_id}).get("Item")
        if not route or "target_price" not in route:
            continue

        target_price = route["target_price"]
        if price < target_price:
            dates = f"{outbound_date} -> {return_date}" if outbound_date and return_date else ""
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"Bajo de precio: {route_id}",
                Message=(
                    f"{airline}: {route_id} {dates} esta en {price} {currency} "
                    f"({stops_desc}, objetivo: {target_price} {currency})"
                ),
            )
            alerts_sent += 1

    return {"alerts_sent": alerts_sent}
