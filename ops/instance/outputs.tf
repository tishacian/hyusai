output "network_id" {
  value = openstack_networking_network_v2.cluster.id
}

output "subnet_id" {
  value = openstack_networking_subnet_v2.cluster.id
}

output "control_plane_private_ips" {
  value = [for n in openstack_compute_instance_v2.control_plane : n.access_ip_v4]
}

output "control_plane_floating_ips" {
  value = [for f in openstack_networking_floatingip_v2.control_plane : f.address]
}

output "worker_private_ips" {
  value = [for n in openstack_compute_instance_v2.worker : n.access_ip_v4]
}

output "ansible_inventory" {
  description = "YAML host file for ops/ansible/inventories/lab."
  value = yamlencode({
    all = {
      children = {
        kube_control_plane = {
          hosts = {
            for idx, n in openstack_compute_instance_v2.control_plane :
            n.name => {
              ansible_host = openstack_networking_floatingip_v2.control_plane[idx].address
              ansible_user = "ubuntu"
              private_ip   = n.access_ip_v4
            }
          }
        }
        kube_workers = {
          hosts = {
            for n in openstack_compute_instance_v2.worker :
            n.name => {
              ansible_host = n.access_ip_v4
              ansible_user = "ubuntu"
              ansible_ssh_common_args = "-o ProxyJump=ubuntu@${openstack_networking_floatingip_v2.control_plane[0].address}"
              private_ip = n.access_ip_v4
            }
          }
        }
        kube_cluster = {
          children = {
            kube_control_plane = {}
            kube_workers       = {}
          }
        }
      }
    }
  })
}
