FROM python:3.14-slim
ARG SOURCE_REVISION=unrecorded
LABEL org.opencontainers.image.source="https://github.com/foivoskar/PDFblinder"
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TMPDIR=/work
RUN apt-get update && apt-get install -y --no-install-recommends ghostscript \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pdfblinder \
    && useradd --uid 10001 --gid 10001 --no-create-home pdfblinder \
    && mkdir /work && chown 10001:10001 /work
WORKDIR /app
COPY pyproject.toml README.md LICENSE SECURITY.md CHANGELOG.md ./
COPY docs ./docs
COPY src ./src
RUN python -m pip install --no-cache-dir .
USER 10001:10001
WORKDIR /work
ENTRYPOINT ["pdfblinder"]
