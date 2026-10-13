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

variable "media_node_pool" {
  description = "LiveKit media pool for Helm livekit.network.mode=hostNetwork. Off by default."
  type = object({
    enabled        = bool
    name           = optional(string, "media")
    vm_size        = optional(string, "Standard_D4s_v5")
    node_count     = optional(number, 1)
    udp_port_start = optional(number, 50000)
    udp_port_end   = optional(number, 50100)
    rtc_tcp_port   = optional(number, 7881)
  })
  default = { enabled = false }
}

variable "livekit_public_ip" {
  description = "Static IP for Helm livekit.network.mode=loadBalancer. Off by default."
  type        = bool
  default     = false
}
