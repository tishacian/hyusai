# Terraform — portable cluster contract

Managed Kubernetes is the CI path. `ops/instance` (Nova + kubeadm) stays as
an optional fallback and is not applied by GitLab.

Two modules expose the same outputs. Helm and Ansible consume only this
contract; they do not care which cloud created the API.

| Output | Use |
|---|---|
| `kubeconfig` (sensitive) | `KUBECONFIG` for `helm upgrade` |
| `ingress_class` | chart `ingress.className` |
| `storage_class` | chart `storageClass` / PVC classes |
| `cluster_name` | labels, inventory |

| Module | First lab | Notes |
|---|---|---|
| `modules/cluster-ovh-mks` | **yes** — `envs/lab-ovh` | OVH Managed Kubernetes |
| `modules/cluster-aks` | twin | same playbook, `envs/lab-aks` when Azure is ready |

State is the GitLab HTTP backend, one state name per env. Nothing under
`*.tfstate` or `*.tfvars` is committed.

```bash
# Local syntax only (no cloud, no state):
terraform -chdir=ops/terraform/modules/cluster-ovh-mks init -backend=false
terraform -chdir=ops/terraform/modules/cluster-ovh-mks validate

# Apply is a GitLab manual job on demo/agentic. Not a local GO.
```
