resource "ovh_cloud_project_kube" "this" {
  service_name = var.service_name
  name         = var.cluster_name
  region       = var.region
  version      = var.kubernetes_version
}

resource "ovh_cloud_project_kube_nodepool" "default" {
  service_name  = var.service_name
  kube_id       = ovh_cloud_project_kube.this.id
  name          = var.nodepool_name
  flavor_name   = var.flavor_name
  desired_nodes = var.desired_nodes
  min_nodes     = var.min_nodes
  max_nodes     = var.max_nodes
}
