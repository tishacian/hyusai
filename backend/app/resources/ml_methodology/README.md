# ML methodology release assets

`probabl-v1.json` adapts selected problem framing, planning, evaluation and audit
practices from [Probabl Skills](https://github.com/probabl-ai/skills/tree/9e1b9870113a0955de3c53f47820af0756dbe84d).
The document records the immutable upstream revision and SHA-256 of the four
source documents read during adaptation. `LICENSE.probabl` contains the original
BSD-3-Clause copyright, conditions and disclaimer and must remain in distributed
images with these assets. This adaptation does not imply Probabl endorsement.

The executable implementation is `app.services.ml_methodology`. It validates
typed, bounded problem inputs locally and returns explicit unknowns, refusals or
a draft of existing Omnirag Flow nodes. It does not install or run the upstream
Skills CLI. Workspace setup, Git, environment management, report synchronization,
Skore Projects and hosted agents are deliberately outside this adaptation.

The two canonical Skills use the existing `tabular_models` capability:

- `ml_problem_frame_v1` records the objective, dataset ID/version, target,
  information available at prediction time, baseline, metric, split and budget.
- `ml_experiment_plan_v1` validates the same definition and proposes bounded
  classic-estimator training nodes followed by `ml_evaluation_review_v1` nodes.
  Publication and execution remain explicit Omnirag operations.

The HTTP equivalents are `POST /ml-models/methodology/problem-frame` and
`POST /ml-models/methodology/experiment-plan`, using the same workspace scope,
Pydantic input and output contracts and service functions. No new storage exists.

Publication freezes the method document, upstream provenance, content digest and
implementation-file digest in `SystemVersion.execution_contract`, through the
existing verified `registry_call` executor. Workspace aliases are pinned too.
The draft's graph-owned training parameters also carry the contract; submission
rechecks dataset version, target/features, protocol, selected family and the
instance timeout against the declared budget. A changed method/runtime is refused
with `ML_METHOD_VERSION_UNAVAILABLE`: preserve the producer image or review and
republish. Upgrading a release cannot silently replace a published method.

The compiler and the training wrapper count the actual candidate nodes, require
the baseline and reject repeated subgraphs. Authoring a `registry_call` alias for
a graph-owned data write is refused at binding and again for older published
bindings (`executor_target_requires_flow_node`). This prevents an alias from
injecting a training/transform configuration after the agent's recommendation
gate. The shared effect list still permits model prediction aliases and both
read-only methodology Skills.

Current limits are explicit: classification/regression, one immutable table,
random holdout with development CV, linear/gradient boosting/random forest/KNN,
automatic preprocessing, no tuning. Temporal, grouped and predefined splits are
blocked. Macro F1 remains a valid framing choice but cannot produce a training
draft until the development metric contract guarantees that exact aggregation.
Memory and prediction latency limits are acceptance criteria, not enforcement
claims. Requested total training time below the current supervisor ceiling is
blocked. Monetary training cost is unavailable, not presumed zero.

Rollback: set `ML_METHODOLOGY_ENABLED=false` on the API and workers, then restart
those processes. Framing, planning, evaluation review and training nodes carrying
a methodology contract return `ML_METHODOLOGY_DISABLED`, including previously
published bindings. AgentLoop stops offering the canonical advice Skills. The
catalog definitions and historical Runs remain readable; ordinary model training,
prediction, model-card evidence and stored artifacts remain available. No data
or catalog rows must be deleted to withdraw the feature.

The fixed 12-mission test corpus covers missing facts, task/metric mismatches,
unknown features, target leakage, unsupported protocols and adversarial prose.
It establishes contract behavior. Operator-time and useful-run improvements need
a separate observed baseline and assisted-workflow evaluation; no productivity
gain is claimed by these tests.
