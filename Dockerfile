FROM python:3.11-slim

# Install the versioned SuperQA CLI release artifact.
RUN pip install --no-cache-dir \
    "https://superqa.blob.core.windows.net/superqa-cli/superqa-cli-v1.0.6.tar.gz"

ENTRYPOINT ["superqa-action"]
