"""Bounded recursive previews resolve every leaf through workspace authorization."""

import json
from dataclasses import replace

import sqlglot
from sqlglot import exp

from app.schemas.data_prep import bind_spec
from app.services.dataops.compiler import compile_prep, literal, quote
from app.services.dataops.typed_compiler import select_step


def compile_preview_graph(db, workspace_id, spec, inputs, *, step_id=None):
    from app.services.dataops.preparation import compile_inputs
    from app.services.dataops.preview import native_schema
    from app.services.dataops.storage import identity_digest
    from app.services.dataops.types import describe
    from app.services.tabular_datasets import resolve_dataset_ref

    try:
        size = len(json.dumps(inputs, ensure_ascii=False, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        raise ValueError("DATAPREP_INPUTS_INVALID") from None
    if size > 1024**2:
        raise ValueError("DATAPREP_PREVIEW_GRAPH_LIMIT")

    if step_id:
        index = next((i for i, step in enumerate(spec.steps) if step.id == step_id), None)
        if index is None:
            raise ValueError("DATAPREP_STEP_UNKNOWN")
        # A broken later draft step must not prevent inspecting an earlier prefix.
        spec = spec.model_copy(update={"steps": spec.steps[: index + 1]})

    if not any(isinstance(ref, dict) and "upstream" in ref for ref in inputs.values()):
        compiled, datasets = compile_inputs(db, workspace_id, spec, inputs)
        return select_step(compiled, step_id), datasets
    leaves, parameters, visiting = {}, {}, set()
    nodes = 0

    def visit(config, references, depth, selected=None):
        nonlocal nodes
        if depth >= 10 or nodes >= 32:
            raise ValueError("DATAPREP_PREVIEW_GRAPH_LIMIT")
        if id(references) in visiting:
            raise ValueError("DATAPREP_PREVIEW_CYCLE")
        visiting.add(id(references))
        index = nodes
        nodes += 1
        if not isinstance(references, dict) or not references or len(references) > 16:
            raise ValueError("DATAPREP_INPUT_PORTS_INVALID")
        schemas, identities, replacements, children = {}, {}, {}, []
        for port, reference in references.items():
            if not isinstance(reference, dict):
                raise ValueError("DATAPREP_INPUTS_INVALID")
            alias = f"__preview_{index}_{port}"
            if "upstream" in reference:
                if set(reference) != {"upstream"}:
                    raise ValueError("DATAPREP_INPUTS_INVALID")
                upstream = reference["upstream"]
                if not isinstance(upstream, dict) or set(upstream) - {
                    "spec",
                    "inputs",
                    "outputs",
                    "output_port",
                }:
                    raise ValueError("DATAPREP_INPUTS_INVALID")
                child_spec = bind_spec(upstream.get("spec"), upstream.get("outputs"))
                child = visit(child_spec, upstream.get("inputs"), depth + 1)
                output_port = upstream.get("output_port", "out")
                if output_port not in {o.port for o in child_spec.outputs}:
                    raise ValueError("DATAPREP_SOURCE_PORT_REQUIRED")
                query = child.sql
                if child_spec.operation == "split":
                    query = f"SELECT {','.join(quote(n) for n in child.columns)} FROM ({query}) WHERE __dp_output={literal(output_port)}"
                children.append((alias, sqlglot.parse_one(query, read="duckdb")))
                schemas[port] = list(child.output_schema)
                identities[port] = {"fingerprint": child.fingerprint, "port": output_port}
            else:
                dataset = resolve_dataset_ref(db, workspace_id=workspace_id, ref=reference)
                if dataset.status != "ready":
                    raise ValueError("DATASET_NOT_READY")
                leaves[alias] = dataset
                schemas[port] = describe(native_schema(dataset))
                identities[port] = {
                    "id": dataset.id,
                    "version": dataset.version,
                    "digest": identity_digest(dataset),
                }
            replacements[port] = alias
        compiled = compile_prep(config, schemas, identities=identities)
        compiled = select_step(compiled, selected)
        for key, value in compiled.preview_parameters.items():
            parameters[f"preview_{index}_{key}"] = value

        def compose(sql):
            tree = sqlglot.parse_one(sql, read="duckdb")
            for table in tree.find_all(exp.Table):
                if table.name in replacements:
                    table.set("this", exp.Identifier(this=replacements[table.name], quoted=True))
            for parameter in tree.find_all(exp.Placeholder):
                if parameter.name in compiled.preview_parameters:
                    parameter.set("this", f"preview_{index}_{parameter.name}")
            if children:
                tree = exp.select("*").from_(tree.subquery("__preview_result"))
                for alias, child in children:
                    tree = tree.with_(alias, as_=child.copy())
            return tree.sql(dialect="duckdb")

        visiting.remove(id(references))
        return replace(
            compiled,
            sql=compose(compiled.sql),
            step_queries={key: compose(sql) for key, sql in compiled.step_queries.items()},
            input_query=compose(compiled.input_query) if compiled.input_query else "",
            preview_parameters=dict(parameters),
        )

    compiled = visit(spec, inputs, 0, step_id)
    return replace(compiled, preview_parameters=parameters), leaves


def sql_export(compiled, spec):
    allowed = not compiled.preview_parameters
    if not allowed:
        return {"sql_export_allowed": False, "sql_export": None, "sql_export_by_port": {}}
    tree = sqlglot.parse_one(compiled.sql, read="duckdb")
    for table in tree.find_all(exp.Table):
        if table.name == "in":
            table.set("this", exp.Identifier(this="input", quoted=True))
    sql = tree.sql(dialect="duckdb")
    ports = {}
    if spec.operation == "split":
        for output in spec.outputs:
            ports[output.port] = (
                f"SELECT {','.join(quote(n) for n in compiled.columns)} FROM ({sql}) WHERE __dp_output={literal(output.port)}"
            )
    else:
        ports["out"] = sql
    return {"sql_export_allowed": True, "sql_export": sql, "sql_export_by_port": ports}
