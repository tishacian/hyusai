# Agentium operations — OpenStack → Kubernetes

This tree starts the Compose → Kubernetes passage. It follows the papAI OPS
split:

| This repo | papAI counterpart | Role |
|---|---|---|
| `ops/instance` | `papAI/OPS/instance` | Terraform: OpenStack networks, security groups, volumes, kube nodes |
| `ops/ansible` | `papAI/OPS/ansible/ansible` | Ansible: cluster bootstrap, then Helm deploy pipelines |
| `ops/helm/agentium` | application chart | The Agentium stack that Compose runs on `omnirag-demo` |

Compose on the demo VM (`docker/compose.agentium.yml`) stays the live path.
Nothing here is a deploy GO.

## Pipeline

```
ops/instance  terraform apply
        ↓  inventory from terraform output
ops/ansible   playbooks/provision-cluster.yml   (kubeadm)
        ↓  kubeconfig
ops/ansible   playbooks/deploy-agentium.yml     (helm upgrade)
        ↓
ops/helm/agentium
```

Images stay digest- or SHA-tagged, same contract as
`docker/compose.agentium.registry.yml`. The first cluster still needs a
registry reachable from the nodes; that is later work, not implied by this
scaffold.

## What v0.1 covers

- OpenStack lab: 1 control-plane VM, N workers, Cinder volumes for
  PostgreSQL / MinIO / Qdrant.
- Helm resources for the Compose services that are always on in production:
  frontend, backend, worker, p4-maintenance, RabbitMQ, PostgreSQL, MinIO,
  Qdrant, Keycloak, migrate Job, ingress (`/`, `/api`, `/kc`).
- Ansible playbooks that install kubeadm/Helm and upgrade the chart.

## Explicitly later

- LiveKit, SFTP, dedicated Celery beat (Compose profiles).
- Replacing in-cluster PostgreSQL / MinIO / Qdrant / Keycloak with managed
  services.
- Magnum or another OpenStack-managed Kubernetes API.

## Checks

```bash
ops/scripts/check-k8s-scaffold.sh
```
