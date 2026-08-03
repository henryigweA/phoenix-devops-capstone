variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "rg-phoenix-dev"
}

variable "location" {
  description = "Azure region to deploy into"
  type        = string
  default     = "southafricanorth"
}