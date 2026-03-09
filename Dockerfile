FROM python:3.11-slim

WORKDIR /app

# Use Aliyun mirror for faster package download in China
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 5000

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

CMD ["python", "web_server.py"]
