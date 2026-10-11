# `ops/ansible` — Helm deploy on a managed cluster

`deploy-agentium.yml` is the only playbook the GitLab k8s path runs. It
talks to localhost, reads `KUBECONFIG` from the Terraform output (or a CI
file variable), and runs `helm upgrade --install`.

`provision-cluster.yml` is the kubeadm bootstrap for `ops/instance`. It is
not in the managed-cluster pipeline.

```bash
export KUBECONFIG=/path/from/terraform/kubeconfig
export AGENTIUM_CI_IMAGES_FILE=/path/to/values-ci-images.yaml

ansible-playbook -i inventories/ci playbooks/deploy-agentium.yml
```

Values layers, in order: `values.yaml`, `values-lab-ovh.yaml` (or
`values-lab-aks.yaml`), then the CI digest overlay. No credentials belong
in the inventory.
