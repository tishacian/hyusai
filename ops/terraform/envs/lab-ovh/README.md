# env `lab-ovh`

First applyable lab. Calls `modules/cluster-ovh-mks`.

```bash
cp terraform.tfvars.example terraform.tfvars   # not committed
# terraform apply is the GitLab job agentium-k8s-apply-lab-ovh, not local.
terraform init -backend=false
terraform validate
```

GitLab protected variables: `OVH_ENDPOINT`, `OVH_APPLICATION_KEY`,
`OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`, `OS_PROJECT_ID` (mapped to
`TF_VAR_service_name` when tfvars is absent).

State name: `agentium-lab-ovh`.
