"""The ML plane's family-neutral parts: knobs, metrics, families, runtimes.

``tabular_ml`` owns the lifecycle a model row goes through; what varies by kind
of model — which tasks, which harness, which image trains it, which knobs a
form shows, which way a metric ranks — is declared here, so a new family is a
declaration and a harness rather than a fork of that lifecycle. Nothing in this
package imports a modelling library at module scope: the API process loads it.
"""
