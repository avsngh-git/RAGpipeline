# Dependency usage review (2026-10-08)

On 2026-10-08 the owner asked for the whole codebase to be checked against the
documentation of each dependency it uses. Six read-only reviews compared our code with the
official documentation, or installed sources, for the pinned versions:
- LangGraph and psycopg;
- FastAPI, Starlette, uvicorn and Pydantic;
- asyncpg, httpx and Qdrant;
- OpenTelemetry and Prometheus;
- the Ollama and OpenAlex APIs;
- sentence-transformers, transformers, PyTorch, bm25s and Docling.

The planning session re-checked the four most serious findings against the code before
acting. The owner approved items 1–9 for fixing. Items 10–12 change retrieval results and
need a planned re-index and re-evaluation. The rest are recorded here for later.

## Fixed (items 1–9)

None of these changes retrieval rankings or answers.

| # | Area | Problem | Change | PR |
| --- | --- | --- | --- | --- |
| 1 | OpenTelemetry | Spans used OpenTelemetry's default `record_exception`, so exception messages and stack traces, which can contain model output (a pydantic `input_value`), reached the JSONL traces and Langfuse at the `none` and `ids` content levels, against ADR-0026. | `get_tracer()` returns a `PrivateTracer`. A failed span records ERROR status and `error.type`, plus `research.error.message` only at `full`; exception events are never recorded. | [#158](https://github.com/avsngh-git/RAGpipeline/pull/158) |
| 2 | FastAPI | A body sent without `Content-Length` that went over 64 KiB returned 400 on model-bound routes. FastAPI 0.141.1 turns any non-`HTTPException` raised while parsing a body into a 400. | The body limit raises a 413 `HTTPException`. | [#159](https://github.com/avsngh-git/RAGpipeline/pull/159) |
| 3 | Starlette | 404 and 405 returned FastAPI's bare `{"detail": …}`, against spec §7.2. | A Starlette `HTTPException` handler uses the error envelope (`not_found`, `method_not_allowed`, `request_too_large`, `invalid_request`) and keeps `Allow`. | [#159](https://github.com/avsngh-git/RAGpipeline/pull/159) |
| 4 | OpenAlex | A merged work's old ID returns a 301 to the new one; the client failed with "unexpected redirect". | `OpenAlexMoved(old, new)`. Citation enrichment follows it once and records `merged_from`. Curated lookups stop with a message naming the new ID. | [#160](https://github.com/avsngh-git/RAGpipeline/pull/160) |
| 5 | OpenAlex | `X-RateLimit-Credits-Used` counts credits ($0.0001 each) but was read as dollars. Searches report `meta.cost_usd`, so the spend ledger was unaffected. | Header costs are converted to dollars. | [#160](https://github.com/avsngh-git/RAGpipeline/pull/160) |
| 6 | LangGraph | Scripted suites and tests used `InMemorySaver()` with LangGraph's default serializer, which allows any type with a warning, unlike production's allow-listed saver. The allow-list also had 13 types the state never held. | One `checkpoint_serializer()` for every saver. The allow-list is the 11 types reachable from `ResearchState`, enforced by `tests/test_checkpoint_allowlist.py`. | [#161](https://github.com/avsngh-git/RAGpipeline/pull/161) |
| 7 | Ollama | No sampling options were sent, so the model file decided them (temperature 1, top_k 20, top_p 0.95, presence penalty 1.5), while `llm_calls` recorded `temperature: None`. | The same values are sent with every call and recorded. A fixed-seed live check gave identical output. The configuration hash changes. | [#162](https://github.com/avsngh-git/RAGpipeline/pull/162) |
| 8 | Ollama | The API's per-call `num_ctx` (32,768) silently overrode Compose's `OLLAMA_CONTEXT_LENGTH` (16,384). | The Compose default is 32,768, with a comment that the two must match. | [#162](https://github.com/avsngh-git/RAGpipeline/pull/162) |
| 9 | PyTorch | PyTorch was pinned nowhere, and a stale `torch-2.12.0+cpu` metadata folder sat beside 2.14.0+cu130. | The `embeddings` extra pins `torch==2.14.0`. Runs record `torch_version`, read without importing torch. The stale folder was moved to `local-reference/env-backup/`. | [#163](https://github.com/avsngh-git/RAGpipeline/pull/163) |

Each PR adds tests, and where possible a test that fails on the old code. Operator-facing
details are in:
- `docs/operations/observability.md` (item 1);
- `docs/operations/phase-2-search.md` (items 2–5 and 9);
- `docs/operations/phase-3-generator.md` (items 6–8).

Two related fixes from the same day came from the development sweep, not this review:
- the API's OpenAlex client stopped after 10 requests per process (PR #156);
- llama-server's 8 GiB prompt cache was bounded to 1 GiB (PR #157).

## Need a re-index and re-evaluation (items 10–12)

Status on 2026-10-08:
- **Item 10 (PR #165):** fixed with no re-index.
  - **Measured effect:** with the same index, dense top-10 results were identical for
    21/21 agent development questions, and top-50 results shared 49.95 of 50.
  - **No rebuild needed:** stored vectors are equally close to fp16 and fp32 encodings.
- **Item 12 (PR #165):** fixed.
- **Item 11:**
  - **New extractions (PR #166):** figure text is kept and labelled `Figure text`
    (owner decision 12).
  - **The existing corpus is unchanged.**
    - In the active snapshot, 14,622 of 44,277 indexed chunks (33%) are figure fragments,
      averaging 14 characters.
    - 1,520 of the 6,070 text sections cited in Phase 2 source alignments are such
      fragments, for example chart values and legend entries. Removing figure text from
      the index would make that judged evidence unreachable.
  - **Why it stays:** removing those fragments would lose judged evidence. Grouping each
    figure's fragments into one evidence unit is a later, measured step.

10. **The gte-modernbert "fp32" profile runs in fp16.** transformers 5.x loads the dtype
    from `config.json`, which says `float16`, when none is passed (`embeddings.py:404-415`).
    The measured Phase 2 v10 vectors were therefore probably fp16. Relabel first. Forcing
    fp32 changes the vectors.
11. **Figure text is indexed as body text.** `iterate_items(..., traverse_pictures=True)`
    (`pdf_extraction.py:178`) yields axis labels, legends and figure OCR, against the
    declared `figure_interpretation: caption-only`. Fixing it needs re-extraction.
12. **The fp16 reranker can run on CPU when no GPU is available**
    (`reranker_models.py:146-192`). The embedder refuses this case; the reranker should too.

## Reliability improvements (not yet done)

- **PostgreSQL:**
  - No `statement_timeout` or `lock_timeout` on the API pool.
  - The checkpoint pool has no connection health check (`check=`) and doesn't fail fast at
    startup.
  - Foreign-key columns hit by run pruning have no indexes.
  - JSONB is decoded by hand in about 15 places.
- **Ollama:**
  - Retry once on 500 or 502.
  - Don't send a repair turn when `done_reason` is not `stop`.
- **httpx:**
  - Separate connect timeouts. The 1,200 s Ollama timeout also applies to connecting.
  - Retry Qdrant connection setup; its writes are idempotent.
- **OpenAlex:**
  - Use the recommended 30 s timeout, and fail fast when the daily budget is spent.
  - Add `ids` to `select` to deduplicate merged and preprint copies (e.g. three ListT5 IDs).
- **Observability:**
  - Process and GC metrics on our registry.
  - Gzip OTLP exports, with smaller batches and truncation that keeps the JSON valid.
  - `service.version`, and `gen_ai.operation.name`.
  - Pre-created label series.
  - Log time taken from `LogRecord.created`.
- **API:**
  - An unhandled error is logged three times.
  - `model_construct` skips validation in about 10 places.
  - The Dockerfile binds `0.0.0.0` while the auth check assumes `127.0.0.1`.
  - Pin uvicorn to one worker, since the rate limiter and run executor are per process.
- **Docling:** drop the deprecated `generate_table_images`, and set `document_timeout`.
- **Transformers:** use `dtype` instead of the deprecated `torch_dtype`.

## Owner decisions (change recorded behaviour or the evaluation baseline)

- **OpenAlex:** keyword discovery uses `corpus=all`, which adds noisier dataset and
  repository records.
- **Ollama prompts:** put the JSON schema in the prompt as well as in `format`, as Ollama
  recommends. This needs a new prompt version.
- **Ollama sampling:** lower the temperature for calls without thinking (evaluate first).
- **Ollama timeouts:** stream thinking calls with an idle timeout instead of one 20-minute
  limit.
- **API errors:** include field locations in 422 validation errors, which changes the
  public error shape.
- **LangGraph:** set `LANGGRAPH_STRICT_MSGPACK=true`.

## Checked and matching the documentation

- **Middleware:** all of it is plain ASGI, not `BaseHTTPMiddleware`.
- **Qdrant:** only the current query endpoints, with payload indexes created before data
  and idempotent `wait=true` writes.
- **PostgreSQL:** advisory locks and the `SKIP LOCKED` work queue are correct.
- **Model loading:** revisions pinned, offline-only, `trust_remote_code=False`, the right
  query and document prefixes, and limits counted before truncation.
- **bm25s:** the same tokenizer for indexing and queries, with mmap loading.
- **LangGraph:** durability `sync` and the recursion limit are fine.
- **Prometheus:** labels are bounded.
- **OpenAlex:** the key is sent as a Bearer header.
