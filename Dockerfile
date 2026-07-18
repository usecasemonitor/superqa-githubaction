FROM python:3.11-slim

# Install SuperQA CLI from Azure Blob (private repo; includes testPlanName API fix)
RUN pip install --no-cache-dir https://superqa.blob.core.windows.net/superqa-cli/superqa-cli-v1.0.3.tar.gz

ENTRYPOINT ["python"]
