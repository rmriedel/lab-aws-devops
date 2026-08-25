# Identidad de mail para mandar las alertas con formato HTML (SNS no soporta
# HTML en el cuerpo, solo texto plano - por eso SES en vez de un topico SNS).
# Se manda de esta misma direccion a esta misma direccion, asi que estando en
# sandbox de SES alcanza con verificar una sola identidad (no hace falta
# pedir salida de sandbox). Requiere el mismo paso manual que antes tenia la
# suscripcion de SNS: click en el mail de verificacion que SES manda al
# aplicar - Terraform no puede completar eso.
resource "aws_ses_email_identity" "alert" {
  email = var.alert_email
}
