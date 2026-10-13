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

# LiveKit media nodes (Helm livekit.network.mode=hostNetwork). Only pods that
# tolerate the taint land here, so the UDP range on their address is LiveKit's.
resource "ovh_cloud_project_kube_nodepool" "media" {
  count = var.media_nodepool.enabled ? 1 : 0

  service_name  = var.service_name
  kube_id       = ovh_cloud_project_kube.this.id
  name          = var.media_nodepool.name
  flavor_name   = var.media_nodepool.flavor_name
  desired_nodes = var.media_nodepool.nodes
  min_nodes     = var.media_nodepool.nodes
  max_nodes     = var.media_nodepool.nodes

  template {
    metadata {
      annotations = {}
      finalizers  = []
      labels = {
        "agentium.io/media" = "livekit"
      }
    }
    spec {
      unschedulable = false
      taints = [{
        key    = "agentium.io/media"
        value  = "livekit"
        effect = "NoSchedule"
      }]
    }
  }
}
