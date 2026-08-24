variable "repo_name" {
  type    = string
  default = "lab-aws-devops"
}

variable "repo_visibility" {
  description = "private o public."
  type        = string
  default     = "private"
}
