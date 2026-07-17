FROM python:3.12-slim

# WITH_BROWSER=1 bakes Chromium in for the FB/X collectors (bigger image).
# The default slim image covers matching + reporting + dashboard.
ARG WITH_BROWSER=0

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_BROWSER" = "1" ]; then \
         playwright install --with-deps chromium; \
       fi

COPY relay/ relay/

ENV RELAY_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8501

CMD ["python", "-m", "relay.cli", "serve", "--port", "8501"]
