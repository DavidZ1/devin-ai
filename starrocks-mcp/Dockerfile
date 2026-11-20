FROM python:3.12-slim

ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["starrocks-mcp"]
