FROM condaforge/miniforge3:26.7.2-0@sha256:eeb947cc87d61d46820b123bd7c26e1cbdc4b182ff7d0331e501a32a936b82e3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONDA_ENV=/opt/conda/envs/research-platform

WORKDIR /app

COPY environment-linux-64.lock /tmp/environment-linux-64.lock
RUN conda create --yes --prefix "${CONDA_ENV}" --file /tmp/environment-linux-64.lock \
    && conda clean --all --yes

ENV PATH="${CONDA_ENV}/bin:${PATH}"

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-build-isolation --no-deps .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "research_platform.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
