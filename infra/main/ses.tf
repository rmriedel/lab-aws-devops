# Identidad de mail del DESTINATARIO (var.alert_email, el Gmail real donde se
# lee todo). Sigue haciendo falta mientras SES este en sandbox: para mandar a
# una direccion sin pedir salida de sandbox, esa direccion tiene que estar
# verificada. Requiere un click en el mail de verificacion que SES manda al
# aplicar - Terraform no puede completar eso.
resource "aws_ses_email_identity" "alert" {
  email = var.alert_email
}

# Identidad de dominio del REMITENTE (var.alert_from_email, ej.
# alertas_precio@rodrigo-riedel.ar) - para mandar "como" esa direccion hace
# falta verificar el DOMINIO, no solo un mail suelto. El verification_token y
# los dkim_tokens se exponen en outputs.tf para que infra/cloudflare los lea
# via remote state y cree el TXT + los 3 CNAME correspondientes - no se
# copian a mano entre los dos roots.
#
# ORDEN DE APPLY (no se puede evitar - la verificacion necesita que el DNS ya
# exista): 1) aplicar este archivo tal cual (identity + dkim, no esperan
# nada). 2) aplicar infra/cloudflare (crea los registros DNS reales). 3)
# recien ahi agregar aws_ses_domain_identity_verification y aplicar de nuevo
# infra/main - ese recurso sondea a AWS hasta confirmar el dominio verificado.
resource "aws_ses_domain_identity" "alert_domain" {
  domain = split("@", var.alert_from_email)[1]
}

resource "aws_ses_domain_dkim" "alert_domain" {
  domain = aws_ses_domain_identity.alert_domain.domain
}

# Sondea a AWS hasta confirmar que el TXT de verificacion ya esta resuelto -
# se agrega recien despues de aplicar infra/cloudflare (paso 2 del orden de
# arriba), si no falla porque el DNS todavia no existe.
resource "aws_ses_domain_identity_verification" "alert_domain" {
  domain = aws_ses_domain_identity.alert_domain.id
}
