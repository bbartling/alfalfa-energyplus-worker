FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY twin twin
COPY tools tools
EXPOSE 8080
CMD ["uvicorn", "twin.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
