# Recepcion (no envio - eso es SES en infra/main): destino de reenvio + regla
# que conecta la direccion custom con ese destino. SPF/DMARC para el ENVIO
# via SES queda fuera de alcance a proposito (ver docstring del plan) -
# revisar aparte si algo cae en spam.
#
# NOTA - dos resources se sacaron a proposito, quedan como pasos manuales:
# - cloudflare_email_routing_settings: bug real del provider v5.24.0 (el
#   ultimo disponible al momento de escribir esto): "mismatch between struct
#   and object: Struct defines fields not found in object:
#   support_subaddress".
# - cloudflare_email_routing_dns (el que escribe MX/SPF): el token de API
#   devuelve 403 "Authentication error" en ese endpoint puntual pase lo que
#   pase con los permisos (probado: DNS:Edit, Email Routing Rules:Edit,
#   Email Routing Addresses:Edit de cuenta, Zone Settings:Edit) - no se
#   encontro el permiso correcto. Se activo a mano desde el dashboard
#   (Email -> Email Routing -> Enable), que usa la sesion completa del
#   usuario en vez del token acotado.
resource "cloudflare_email_routing_address" "forward_target" {
  account_id = data.cloudflare_zone.this.account.id
  email      = var.forward_to_email
}

resource "cloudflare_email_routing_rule" "alertas" {
  zone_id  = data.cloudflare_zone.this.zone_id
  name     = "Reenviar ${var.alert_local_part}@${var.domain}"
  enabled  = true
  priority = 0

  matchers = [{
    type  = "literal"
    field = "to"
    value = "${var.alert_local_part}@${var.domain}"
  }]

  actions = [{
    type  = "forward"
    value = [cloudflare_email_routing_address.forward_target.email]
  }]
}
