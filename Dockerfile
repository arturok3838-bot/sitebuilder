# Лёгкий образ для облака без видеокарты. Для фото/видео нужен GPU-образ (см. README).
FROM python:3.12-slim
WORKDIR /app
COPY requirements-lite.txt .
RUN pip install --no-cache-dir -r requirements-lite.txt
COPY . .
EXPOSE 7860
CMD ["python", "-m", "arturokai.server", "--host", "0.0.0.0", "--port", "7860"]
