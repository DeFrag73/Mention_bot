# Використовуємо базовий образ Python з конкретною версією
FROM python:3.12-slim

# Встановлюємо робочу директорію в контейнері
WORKDIR /mentionBot

# Встановлюємо змінні середовища
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/mentionBot

# Встановлюємо необхідні системні пакети
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо спочатку тільки файл з залежностями
COPY requirements.txt .

# Встановлюємо залежності
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt &&\
    pip install --no-cache-dir python-dotenv

# Змінюємо права до того, як змінити користувача
RUN mkdir -p /mentionBot && \
    chmod -R 777 /mentionBot

# Копіюємо файли з правильними правами
COPY --chown=appuser:appuser . .

# Встановлюємо права
RUN chmod -R 777 /mentionBot

# Створюємо користувача та перемикаємося на нього
RUN adduser --disabled-password --gecos "" appuser && \
    adduser appuser sudo && \
    echo "appuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER appuser

# Встановлюємо команду, яка буде виконана при старті контейнера
CMD ["python", "main.py"]