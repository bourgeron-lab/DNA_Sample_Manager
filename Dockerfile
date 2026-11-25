# Image de DNA Sample Manager (pour Kubernetes : voir deploy/kubernetes/KUBERNETES.md)
#   docker build -t <registre>/dna-sample-manager:<version> .
#
# La base n'est JAMAIS dans l'image : elle est sur un volume monté en /data,
# les sauvegardes sur un volume monté en /backups.

# --- Construction de l'environnement Python (versions exactes de uv.lock) ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- Image finale : Python + l'environnement, sans uv ni outils de build ---
FROM python:3.12-slim-bookworm
RUN groupadd --system --gid 10001 dnasm \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent dnasm \
 && install -d -o 10001 -g 10001 -m 700 /data /backups
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 5003
ENTRYPOINT ["dna-sample-manager"]
# Derrière l'Ingress : écoute sur toutes les interfaces du pod, en-têtes X-Forwarded-*
# acceptés (seul l'Ingress joint le pod, voir networkpolicy.yaml)
CMD ["/data", "--host", "0.0.0.0", "--port", "5003", "--behind-proxy", "--trusted-proxy", "*", \
     "--no-browser", "--backup-dir", "/backups", "--keep", "30", "--backup-interval", "24"]
