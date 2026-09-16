# `ops/instance` — Nova + kubeadm fallback

Optional. The GitLab path uses `ops/terraform/envs/lab-ovh` (OVH MKS) or
`envs/lab-aks`. This directory still creates networks, security groups,
volumes and VMs when someone explicitly wants kubeadm.

```bash
cp terraform.tfvars.example terraform.tfvars   # not committed
terraform init
terraform plan
# terraform apply   # explicit GO only; not a CI job
terraform output -raw ansible_inventory > ../ansible/inventories/lab/terraform_inventory.yml
```

Then `provision-cluster.yml`. `deploy-agentium.yml` still expects
`KUBECONFIG`, not `/etc/kubernetes/admin.conf`.

