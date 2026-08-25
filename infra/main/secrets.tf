# API key de SerpApi (motor google_flights) - nunca va como env var plana ni
# se escribe en ningun archivo trackeado por git. Se pasa por
# terraform.tfvars (gitignored), igual que alert_email.
resource "aws_secretsmanager_secret" "serpapi_api_key" {
  name = "${var.project_name}-serpapi-api-key"
}

resource "aws_secretsmanager_secret_version" "serpapi_api_key" {
  secret_id     = aws_secretsmanager_secret.serpapi_api_key.id
  secret_string = var.serpapi_api_key
}
