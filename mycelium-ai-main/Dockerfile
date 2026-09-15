FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY coordinator ./coordinator
COPY node_client ./node_client
RUN pip install --no-cache-dir .
RUN mkdir -p /data
ENV MYCELIUM_DATABASE_PATH=/data/mycelium.db
EXPOSE 8000
CMD ["uvicorn", "coordinator.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
