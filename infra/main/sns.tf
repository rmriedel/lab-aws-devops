resource "aws_sns_topic" "price_alerts" {
  name = "${var.project_name}-price-alerts"
}

# La suscripción queda "pending confirmation" hasta que se hace click en el
# link que llega al mail - Terraform no puede completar ese paso.
resource "aws_sns_topic_subscription" "price_alerts_email" {
  topic_arn = aws_sns_topic.price_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
