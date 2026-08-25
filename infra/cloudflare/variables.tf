variable "cloudflare_api_token" {
  description = "API token de Cloudflare (dash.cloudflare.com -> My Profile -> API Tokens), scope Zone:DNS:Edit + Zone:Email Routing Addresses:Edit sobre la zona del dominio. Sensible - se pasa por terraform.tfvars (gitignored)."
  type        = string
  sensitive   = true
}

variable "domain" {
  description = "Dominio delegado a Cloudflare donde vive el remitente de las alertas."
  type        = string
  default     = "rodrigo-riedel.ar"
}

variable "alert_local_part" {
  description = "Parte local (antes del @) de la direccion que manda las alertas - tiene que coincidir con var.alert_from_email en infra/main."
  type        = string
  default     = "alertas_precio"
}

variable "forward_to_email" {
  description = "A donde reenvia Cloudflare Email Routing lo que llegue a <alert_local_part>@<domain> - el Gmail real donde se lee todo."
  type        = string
}
