variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "devops-lab"
}

variable "app_port" {
  description = "Puerto en el que escucha la app dentro del contenedor"
  type        = number
  default     = 8080
}

variable "my_ip_cidr" {
  description = "Tu IP pública en formato CIDR (ej: 200.10.20.30/32)."
  type        = string
}

variable "fargate_cpu" {
  description = "vCPU units. 256 = 0.25 vCPU (el mínimo de Fargate)"
  type        = number
  default     = 256
}

variable "fargate_memory" {
  description = "MB de memoria. 512 = mínimo compatible con 256 CPU"
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Cuántas tasks corren. Poné 0 para 'apagar' el servicio sin destruir infra."
  type        = number
  default     = 1
}

variable "github_repo" {
  description = "Repo de GitHub autorizado a asumir el rol OIDC, formato 'org/repo'"
  type        = string
}

variable "log_retention_days" {
  type    = number
  default = 3
}
