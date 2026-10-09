FROM python:3.11-slim

# Install the versioned SuperQA CLI release artifact.
RUN pip install --no-cache-dir \
    "https://github.com/engineering-sqa/superqa-tar/releases/download/v1.0.6/superqa-cli-v1.0.6.tar.gz"

ENTRYPOINT ["superqa-action"]
