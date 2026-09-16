data "openstack_images_image_v2" "os" {
  name        = var.image_name
  most_recent = true
}

locals {
  az = var.az != "" ? var.az : null
}

resource "openstack_compute_instance_v2" "control_plane" {
  count           = var.control_plane_count
  name            = "${var.name}-cp-${count.index + 1}"
  image_id        = data.openstack_images_image_v2.os.id
  flavor_name     = var.flavor_control_plane
  key_pair        = var.keypair_name
  security_groups = [openstack_networking_secgroup_v2.cluster.name]
  availability_zone = local.az

  network {
    uuid = openstack_networking_network_v2.cluster.id
  }

  metadata = {
    role    = "control-plane"
    product = "agentium"
  }
}

resource "openstack_compute_instance_v2" "worker" {
  count           = var.worker_count
  name            = "${var.name}-wk-${count.index + 1}"
  image_id        = data.openstack_images_image_v2.os.id
  flavor_name     = var.flavor_worker
  key_pair        = var.keypair_name
  security_groups = [openstack_networking_secgroup_v2.cluster.name]
  availability_zone = local.az

  network {
    uuid = openstack_networking_network_v2.cluster.id
  }

  metadata = {
    role    = "worker"
    product = "agentium"
  }
}

resource "openstack_networking_floatingip_associate_v2" "control_plane" {
  count       = var.control_plane_count
  floating_ip = openstack_networking_floatingip_v2.control_plane[count.index].id
  port_id     = openstack_compute_instance_v2.control_plane[count.index].network[0].port
}
