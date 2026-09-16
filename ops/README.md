# Agentium operations — managed Kubernetes

Terraform creates a managed cluster. Ansible only runs Helm. The chart is
the same on OVH MKS and AKS. Compose on the demo VM
(`docker/compose.agentium.yml`) stays the live path.

```
ops/terraform/envs/lab-ovh   terraform apply   (GitLab manual)
        ↓ kubeconfig, ingress_class, storage_class
ops/scripts/build-lab-images.sh                 (digest push)
        ↓ values-ci-images.yaml
ops/ansible  playbooks/deploy-agentium.yml      (helm upgrade --install)
        ↓
ops/helm/agentium
        ↓
GET /health/live and /healthz via ingress
```

`ops/instance` + `provision-cluster.yml` remain the optional Nova + kubeadm
fallback. GitLab does not apply that path.

## Contract

Both Terraform modules expose `kubeconfig`, `ingress_class`, `storage_class`,
`cluster_name`. Helm values per env (`values-lab-ovh.yaml`,
`values-lab-aks.yaml`) carry the class names. Images in CI are `@sha256:`
references, never `:local`.

## Checks

```bash
ops/scripts/check-k8s-scaffold.sh
```

Apply, image push, and Helm upgrade are GitLab jobs on `demo/agentic`. They
are not a local GO.
