# Knowledge Guides

Knowledge Guides are versioned Markdown notes attached to a workspace Knowledge Scope or a Knowledge Collection.

They are used to explain how raw data should be interpreted without modifying the raw documents. Typical examples include data dictionaries, column semantics, unit conventions, extraction caveats, and business vocabulary.

## Contract

- A guide targets either a `scope` key or a `collection` slug.
- Edits create a new current version; previous versions remain stored.
- Only `published` current guides are injected into retrieval and chat.
- Guides are emitted as source type `knowledge_guide`, distinct from document chunks.
- Guide changes are audited with `knowledge.guide.created` and `knowledge.guide.updated`.

## Runtime Use

At retrieval time Agentium:

1. Resolves the active Knowledge Scope and collection slugs.
2. Loads published guides attached to that scope and those collections.
3. Adds guide text as query-expansion hints.
4. Prepends guide Markdown to the prompt context as a distinct source.
5. Keeps raw document retrieval and citations intact.

This lets a workspace add interpretation context such as:

```md
# NON-WOVENS France Excel data dictionary

In sheets named `Def strips`, column A contains label codes (`A`, `B`, `C`, ...).
Column B contains the numeric value associated with each label.

Example:
- `A2=B`
- `B2=85`
- Rendered extraction: `B = 85`

Do not infer units unless the source sheet explicitly provides them.
```

## API

- `GET /api/v1/knowledge/guides`
- `POST /api/v1/knowledge/guides`
- `PATCH /api/v1/knowledge/guides/{guide_key}`
- `GET /api/v1/knowledge/guides/effective`

The UI can later expose this as a Markdown editor under Workspace Settings > Chat & Knowledge.
