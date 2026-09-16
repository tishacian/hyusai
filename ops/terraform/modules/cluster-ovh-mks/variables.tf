variable "service_name" {
  description = "OVH Public Cloud project ID (service name)."
  type        = string
}

variable "cluster_name" {
  description = "Managed Kubernetes cluster name."
  type        = string
}

variable "region" {
  description = "OVH region that hosts the MKS control plane (for example GRA11)."
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version advertised by OVH MKS (major.minor)."
  type        = string
  default     = "1.31"
}

variable "nodepool_name" {
  description = "Default node pool name."
  type        = string
  default     = "default"
}

variable "flavor_name" {
  description = "Nova flavor for worker nodes."
  type        = string
  default     = "b3-8"
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
  description = "IngressClass the Helm chart should target. OVH labs install ingress-nginx."
  type        = string
  default     = "nginx"
}

variable "storage_class" {
  description = "CSI StorageClass available on OVH MKS. Not cinder-csi from kubeadm."
  type        = string
  default     = "csi-cinder-high-speed"
}
