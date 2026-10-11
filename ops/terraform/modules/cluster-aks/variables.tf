variable "resource_group_name" {
  type = string
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "cluster_name" {
  type = string
}

variable "dns_prefix" {
  type    = string
  default = ""
}

variable "kubernetes_version" {
  description = "AKS version (major.minor or major.minor.patch). Empty lets Azure pick."
  type        = string
  default     = null
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
  description = "Create an attached ACR and grant AcrPull to the kubelet identity."
  type        = bool
  default     = false
}

variable "acr_name" {
  description = "Globally unique ACR name. Required when create_acr is true."
  type        = string
  default     = ""
}

variable "ingress_class" {
  description = "Application Routing add-on class, or nginx if that chart is installed."
  type        = string
  default     = "webapprouting.kubernetes.azure.com"
}

variable "storage_class" {
  description = "Azure CSI StorageClass. csi-cinder is not available on AKS."
  type        = string
  default     = "managed-csi"
}

variable "enable_web_app_routing" {
  type    = bool
  default = true
}
