# Serving environment

The image uses `environment-serving-linux-64.lock`, a Linux x86-64 explicit
Conda lock with CPU PyTorch and the pinned Transformers and Sentence Transformers
runtime. The slim `environment-linux-64.lock` remains the environment for CI
tests and development. Model weights are downloaded separately and are not part
of the image.

## Regenerate the Conda lock

Resolve and create the environment on Linux x86-64, then export the explicit
package URLs:

```bash
conda env create --name sci_research_agent_serving --file environment-serving.yaml
conda list --explicit --name sci_research_agent_serving > environment-serving-linux-64.lock
```

The accepted `mcp=2.3.0` Conda package conflicts with the conda-forge
`huggingface_hub=1.33.0` build metadata. The environment file therefore installs
that exact Hub version from PyPI, and `requirements-serving.txt` pins its wheel
hash for the Docker build. The explicit lock contains the Conda packages; the
hash-pinned requirements file locks this additional wheel. The solve selected
`pytorch-cpu` 2.14.1 for the `pytorch-cpu=2.14` request.

The image uses the serving lock and installs the hash-pinned runtime wheels in
`requirements-bm25s.txt`, `requirements-serving.txt`, and
`requirements-langgraph.txt` before installing the local package. Rebuild and
scan it with:

```bash
docker build --platform linux/amd64 -t scientific-research-platform:serving .
docker image inspect scientific-research-platform:serving --format '{{.Size}}'
conda run --name sci_research_agent_serving python -m pip check
conda run -n sci_research_agent python -m pip_audit \
  --path /path/to/sci_research_agent_serving
trivy image --severity HIGH,CRITICAL --ignore-unfixed scientific-research-platform:serving
```

Run the Python dependency checks against the freshly solved serving prefix
before packaging; replace the audit path with that Conda environment's prefix.
The final image removes pip after installation, so those commands are not
available inside the final container.

The pinned embedding and reranker revisions are recorded in
`benchmarks/phase2/frozen-profile-v10-qdrant.toml`. Download those revisions into
the runtime Hugging Face cache before starting the API; the application model
adapters load local files only.

## Owner GPU environment

The owner's `sci_research_agent` environment is a CUDA build for RTX 3050 GPU
research runs. The serving lock uses CPU PyTorch so a reviewer can run the image
without an NVIDIA runtime. Both environments use the same Transformers,
Sentence Transformers, Hub, tokenizer, and safetensors versions. The image does
not include Docling or the ingestion worker.

The frozen reranker precision remains fp16 for the measured CUDA profile. Its
loader uses fp32 for CPU inference, where half precision is not a supported
runtime path; the CPU scores are produced by the same pinned model and weights.

## Reranker precision on CPU

The profile's `fp16` precision applies on CUDA; on CPU the reranker runs in
`fp32`. Research runs record the actual device and precision as
`reranker_runtime` in their provenance and effective configuration. CPU scores
can differ in the last digits, so benchmark numbers come from the GPU host.

## Build record

The serving environment was solved on Linux x86-64 with Conda 26.7.1. The
resolved package URLs are in `environment-serving-linux-64.lock`; the CPU
PyTorch solve selected 2.14.1. The image built as `linux/amd64` and is
4,220,504,908 bytes (4.22 GB, 3.93 GiB).

For the model check, an empty `HF_HOME` volume was mounted into the image. The
two model IDs and revisions were read from
`benchmarks/phase2/frozen-profile-v10-qdrant.toml`, downloaded at those revisions,
then loaded with the project embedding and reranker adapters on CPU. One
synthetic sentence produced a 768-dimensional embedding and one synthetic pair
produced one finite reranker score. No source text or model output was saved.
The P6-02 pull request records the command and concise output summary.

`pip check` reported no broken requirements. `pip-audit` reported no known
vulnerabilities for the solved serving environment. Trivy 0.75.0 reported no
HIGH or CRITICAL findings in the scanned Ubuntu and Python packages. Trivy
currently reports Conda package records for SBOM only and does not vulnerability
scan them; hosted CI runs the repository's pinned Trivy action as well.
