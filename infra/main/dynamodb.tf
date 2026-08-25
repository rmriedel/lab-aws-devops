# Rutas vigiladas: origin/destination/target_price/active se manejan como
# atributos schemaless via `aws dynamodb put-item`, no hace falta redeploy
# para agregar o sacar una ruta.
resource "aws_dynamodb_table" "watched_routes" {
  name         = "${var.project_name}-watched-routes"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "route_id"

  attribute {
    name = "route_id"
    type = "S"
  }
}

# Historial de precios. Stream habilitado: dispara el Lambda price_alert
# en cada escritura nueva.
resource "aws_dynamodb_table" "flight_prices" {
  name         = "${var.project_name}-flight-prices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "route_id"
  range_key    = "scraped_at"

  attribute {
    name = "route_id"
    type = "S"
  }

  attribute {
    name = "scraped_at"
    type = "S"
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"
}
