resource "openstack_blockstorage_volume_v3" "postgres" {
  name              = "${var.name}-pg"
  size              = var.volume_size_gb.postgres
  availability_zone = local.az
}

resource "openstack_blockstorage_volume_v3" "minio" {
  name              = "${var.name}-minio"
  size              = var.volume_size_gb.minio
  availability_zone = local.az
}

resource "openstack_blockstorage_volume_v3" "qdrant" {
  name              = "${var.name}-qdrant"
  size              = var.volume_size_gb.qdrant
  availability_zone = local.az
}

# Attach data volumes to the first worker. The Helm chart still uses
# Kubernetes PVCs; these Cinder disks are the OpenStack-side reservation
# that a CSI class can bind later.
resource "openstack_compute_volume_attach_v2" "postgres" {
  count       = var.worker_count > 0 ? 1 : 0
  instance_id = openstack_compute_instance_v2.worker[0].id
  volume_id   = openstack_blockstorage_volume_v3.postgres.id
}

resource "openstack_compute_volume_attach_v2" "minio" {
  count       = var.worker_count > 0 ? 1 : 0
  instance_id = openstack_compute_instance_v2.worker[0].id
  volume_id   = openstack_blockstorage_volume_v3.minio.id
}

resource "openstack_compute_volume_attach_v2" "qdrant" {
  count       = var.worker_count > 0 ? 1 : 0
  instance_id = openstack_compute_instance_v2.worker[0].id
  volume_id   = openstack_blockstorage_volume_v3.qdrant.id
}
