# `ops/ansible` — cluster bootstrap and Helm pipelines

Mirrors `papAI/OPS/ansible/ansible`: playbooks are the deploy pipeline,
roles do the work, inventories come from Terraform.

```bash
# After ops/instance apply:
# terraform -chdir=../instance output -raw ansible_inventory \
#   > inventories/lab/terraform_inventory.yml

ansible-playbook playbooks/provision-cluster.yml
ansible-playbook playbooks/deploy-agentium.yml
```

`provision-cluster.yml` is the kubeadm hook. Package pins and the worker
join token stay in inventory/group_vars — they are environment secrets,
not chart values.

`deploy-agentium.yml` is the Helm upgrade. It is the only playbook that
touches the Agentium release object.
