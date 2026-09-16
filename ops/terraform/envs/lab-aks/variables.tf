variable "resource_group_name" {
  type    = string
  default = "rg-agentium-lab-aks"
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "cluster_name" {
  type    = string
  default = "agentium-lab-aks"
}

variable "dns_prefix" {
  type    = string
  default = "agentium-lab-aks"
}

variable "kubernetes_version" {
  type    = string
  default = null
}

variable "node_count" {
  type    = number
  default = 3
}

variable "vm_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "create_acr" {
  type    = bool
  default = false
}

variable "acr_name" {
  description = "Globally unique ACR name (alphanumeric)."
  type        = string
  default     = ""
}

variable "ingress_class" {
  type    = string
  default = "webapprouting.kubernetes.azure.com"
}

variable "storage_class" {
  type    = string
  default = "managed-csi"
}

variable "enable_web_app_routing" {
  type    = bool
  default = true
}
