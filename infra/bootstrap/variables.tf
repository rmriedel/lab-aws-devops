variable "aws_region" {
  description = "Región de AWS donde se crea todo el lab"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Nombre corto del proyecto, usado como prefijo de recursos"
  type        = string
  default     = "devops-lab"
}
