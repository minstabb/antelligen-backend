# 1. uv 바이너리 가져오기
FROM ghcr.io/astral-sh/uv:latest AS uv_bin
FROM python:3.13-slim

# 2. uv 및 필수 도구 설정
COPY --from=uv_bin /uv /bin/uv
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# 3. wait-for-it.sh 추가
RUN curl -o /wait-for-it.sh https://raw.githubusercontent.com/vishnubob/wait-for-it/master/wait-for-it.sh \
    && chmod +x /wait-for-it.sh

WORKDIR /app

# 4. 패키지 설치
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
EXPOSE 33333

# 5. CMD 하나로 통합
CMD ["/wait-for-it.sh", "mysql:3306", "--", \
     "/wait-for-it.sh", "redis:6379", "--", \
     "/wait-for-it.sh", "postgres:5432", "--", \
     "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "33333"]
