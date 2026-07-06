# Financial Semantic Obfuscation Gateway — zero-dependency image.
# The app is pure Python 3 stdlib, so there is nothing to pip install.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Generate the synthetic sample dataset at build time so the demo works immediately.
RUN python3 scripts/generate_sample_data.py

# Bind to all interfaces inside the container (host stays 127.0.0.1 by default outside Docker).
ENV GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=8770 \
    PYTHONUNBUFFERED=1

EXPOSE 8770

# To use a real model instead of the deterministic mock, pass:
#   -e OPENAI_API_KEY=sk-...  [-e OPENAI_BASE_URL=...]  [-e GATEWAY_MODEL=gpt-4o-mini]
CMD ["python3", "scripts/serve.py"]
