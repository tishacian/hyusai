variable "name" {
  type        = string
  description = "Prefix for every OpenStack resource (network, VMs, volumes)."
  default     = "agentium-lab"
}

variable "os_auth_url" {
  type        = string
  description = "OpenStack Keystone URL."
}

variable "os_region" {
  type    = string
  default = "RegionOne"
}

variable "os_tenant_name" {
  type = string
}

variable "os_username" {
  type = string
}

variable "os_password" {
  type      = string
  sensitive = true
}

variable "os_insecure" {
  type    = bool
  default = false
}

variable "external_network_id" {
  type        = string
  description = "Public / provider network used for the router and floating IPs."
}

variable "dns_nameservers" {
  type    = list(string)
  default = ["1.1.1.1", "8.8.8.8"]
}

variable "cidr" {
  type    = string
  default = "10.42.0.0/24"
}

variable "image_name" {
  type        = string
  description = "Glance image for kube nodes (Ubuntu 22.04 / 24.04)."
}

variable "flavor_control_plane" {
  type    = string
  default = "m1.large"
}

variable "flavor_worker" {
  type    = string
  default = "m1.large"
}

variable "keypair_name" {
  type        = string
  description = "Existing Nova keypair injected into the VMs."
}

variable "worker_count" {
  type    = number
  default = 2
}

variable "control_plane_count" {
  type        = number
  default     = 1
  description = "v0.1 is a single control plane. Raise only with an etcd/HA playbook."
}

variable "ssh_cidr" {
  type        = string
  default     = "0.0.0.0/0"
  description = "Source CIDR allowed to SSH. Tighten before any shared environment."
}

variable "volume_size_gb" {
  type = object({
    postgres = number
    minio    = number
    qdrant   = number
  })
  default = {
    postgres = 50
    minio    = 100
    qdrant   = 50
  }
}

variable "az" {
  type        = string
  default     = ""
  description = "Optional availability zone for volumes and instances."
}
