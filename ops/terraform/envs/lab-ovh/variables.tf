variable "service_name" {
  description = "OVH Public Cloud project ID. CI maps OS_PROJECT_ID here when unset in tfvars."
  type        = string
}

variable "cluster_name" {
  type    = string
  default = "agentium-lab-ovh"
}

variable "region" {
  type    = string
  default = "GRA11"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "nodepool_name" {
  type    = string
  default = "default"
}

variable "flavor_name" {
  type    = string
  default = "b3-8"
}

variable "desired_nodes" {
  type    = number
  default = 3
}

variable "min_nodes" {
  type    = number
  default = 3
}

variable "max_nodes" {
  type    = number
  default = 3
}

variable "ingress_class" {
  type    = string
  default = "nginx"
}

variable "storage_class" {
  type    = string
  default = "csi-cinder-high-speed"
}

variable "media_nodepool" {
  description = "LiveKit media pool for Helm livekit.network.mode=hostNetwork. Off by default."
  type = object({
    enabled     = bool
    name        = optional(string, "media")
    flavor_name = optional(string, "b3-8")
    nodes       = optional(number, 1)
  })
  default = { enabled = false }
}
