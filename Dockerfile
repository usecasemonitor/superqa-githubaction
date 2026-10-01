FROM python:3.11-slim

# Install SuperQA CLI from Azure Blob (private repo; includes testPlanName API fix)
RUN pip install --no-cache-dir https://superqa.blob.core.windows.net/superqa-cli/superqa-cli-v1.0.5.tar.gz#sha256=056d8f78c6a37c7fde910821f38fa87ddc76b33b6ae58cbf3498a622dcb23638

COPY entrypoint.py /action/entrypoint.py

ENTRYPOINT ["python", "/action/entrypoint.py"]
