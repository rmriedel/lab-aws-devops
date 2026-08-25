variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "devops-lab"
}

variable "serpapi_api_key" {
  description = "API key de SerpApi (serpapi.com) para consultar el motor google_flights. Sensible - no tiene default, se pasa por terraform.tfvars (gitignored)."
  type        = string
  sensitive   = true
}

variable "github_repo" {
  description = "Repo de GitHub autorizado a asumir el rol OIDC, formato 'org/repo'"
  type        = string
}

variable "log_retention_days" {
  type    = number
  default = 3
}

variable "alert_email" {
  description = "Email que recibe las alertas de baja de precio (suscripción SNS, requiere confirmación manual post-apply)"
  type        = string
}

variable "scrape_schedule_expression" {
  description = "Expresión de EventBridge Scheduler para el chequeo de precios. Cada corrida ya barre un rango de fechas completo, no hace falta alta frecuencia."
  type        = string
  default     = "rate(1 day)"
}

variable "price_drop_check_enabled" {
  description = "ENABLED/DISABLED - interruptor general del schedule. Arranca en DISABLED hasta validar el pipeline a mano."
  type        = string
  default     = "DISABLED"
}
