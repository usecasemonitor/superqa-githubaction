FROM python:3.11-slim

# Pin both the release and digest so a replaced artifact cannot silently run.
RUN pip install --no-cache-dir \
    "https://superqa.blob.core.windows.net/superqa-cli/superqa-cli-v1.0.6.tar.gz#sha256=89236c0da1fdf05079fb5f8a98ecc1ddfe040dbfcf8ae198103875d46b599947"

ENTRYPOINT ["superqa-action"]
