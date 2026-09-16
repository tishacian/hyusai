module "cluster" {
  source = "../../modules/cluster-ovh-mks"

  service_name       = var.service_name
  cluster_name       = var.cluster_name
  region             = var.region
  kubernetes_version = var.kubernetes_version
  nodepool_name      = var.nodepool_name
  flavor_name        = var.flavor_name
  desired_nodes      = var.desired_nodes
  min_nodes          = var.min_nodes
  max_nodes          = var.max_nodes
  ingress_class      = var.ingress_class
  storage_class      = var.storage_class
}
