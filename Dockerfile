FROM python:3.12-slim
WORKDIR /app
COPY auction_monitor ./auction_monitor
COPY web ./web
COPY samples ./samples
RUN mkdir -p /app/data
ENV APP_HOST=0.0.0.0 APP_PORT=8080 DATABASE_PATH=/app/data/auction_monitor.sqlite3 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "auction_monitor.cli", "serve"]
