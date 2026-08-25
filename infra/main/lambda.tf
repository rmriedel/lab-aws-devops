data "archive_file" "flight_price_check" {
  type        = "zip"
  source_dir  = "${path.module}/../../apps/flight_price_check"
  output_path = "${path.module}/build/flight_price_check.zip"
}

data "archive_file" "price_alert" {
  type        = "zip"
  source_dir  = "${path.module}/../../apps/price_alert"
  output_path = "${path.module}/build/price_alert.zip"
}

resource "aws_cloudwatch_log_group" "flight_price_check" {
  name              = "/aws/lambda/${var.project_name}-flight-price-check"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "price_alert" {
  name              = "/aws/lambda/${var.project_name}-price-alert"
  retention_in_days = var.log_retention_days
}

# Sin dependencias de terceros (solo stdlib + boto3, que ya viene en el
# runtime de Lambda) para no necesitar un paso de build/pip - el zip de
# archive_file alcanza. Timeout alto: barre ~12 fechas por ruta con 2
# llamadas one-way cada una (~24), mas hasta 8 llamadas extra si busca
# combos self-transfer para acortar escalas largas - hasta ~32 llamadas
# HTTP secuenciales a SerpApi por ruta.
resource "aws_lambda_function" "flight_price_check" {
  function_name    = "${var.project_name}-flight-price-check"
  role             = aws_iam_role.flight_price_check_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  filename         = data.archive_file.flight_price_check.output_path
  source_code_hash = data.archive_file.flight_price_check.output_base64sha256
  timeout          = 600

  environment {
    variables = {
      WATCHED_ROUTES_TABLE = aws_dynamodb_table.watched_routes.name
      FLIGHT_PRICES_TABLE  = aws_dynamodb_table.flight_prices.name
      RAW_BUCKET           = aws_s3_bucket.scrape_raw.bucket
      SERPAPI_SECRET_ARN   = aws_secretsmanager_secret.serpapi_api_key.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.flight_price_check]
}

resource "aws_lambda_function" "price_alert" {
  function_name    = "${var.project_name}-price-alert"
  role             = aws_iam_role.price_alert_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  filename         = data.archive_file.price_alert.output_path
  source_code_hash = data.archive_file.price_alert.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      WATCHED_ROUTES_TABLE = aws_dynamodb_table.watched_routes.name
      ALERT_FROM_EMAIL     = var.alert_from_email
      ALERT_TO_EMAIL       = var.alert_email
    }
  }

  depends_on = [aws_cloudwatch_log_group.price_alert]
}

# batch_size > 1 + ventana de batching: si flight_price_check escribe varias
# rutas en la misma corrida, price_alert las recibe juntas en una sola
# invocacion y manda UN mail con todas en vez de uno por ruta.
resource "aws_lambda_event_source_mapping" "flight_prices_stream" {
  event_source_arn                   = aws_dynamodb_table.flight_prices.stream_arn
  function_name                      = aws_lambda_function.price_alert.arn
  starting_position                  = "LATEST"
  batch_size                         = 20
  maximum_batching_window_in_seconds = 30
}
