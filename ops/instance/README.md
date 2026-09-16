# `ops/instance` — OpenStack with Terraform

Mirrors `papAI/OPS/instance`: this directory is the only place that creates
networks, security groups, volumes and VMs for an Agentium Kubernetes lab.

```bash
cp terraform.tfvars.example terraform.tfvars   # not committed
terraform init
terraform plan
# terraform apply   # explicit GO only
terraform output -raw ansible_inventory > ../ansible/inventories/lab/terraform_inventory.yml
```

v0.1 is kubeadm on Nova VMs, not Magnum. A managed Kubernetes API can replace
`nodes.tf` later without changing the Helm chart.
