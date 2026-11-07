#!/usr/bin/env bash
# 知音 Web 原型部署脚本：在服务器 ~/zhiyin 目录下执行
# 依赖：infra 网络与共用中间件（见 /opt/infra/run-infra.sh）
set -e
cd "$(dirname "$0")"

echo "== 1. build image"
docker build -t zhiyin-fastapi:latest .

echo "== 2. run container (512m / 1.0 配额，接入 infra 网络)"
docker rm -f zhiyin-fastapi 2>/dev/null || true
docker run -d --name zhiyin-fastapi --restart unless-stopped \
  --network infra_infra_network \
  -p 8014:8000 \
  --memory 512m --cpus 1.0 \
  --env-file .env \
  zhiyin-fastapi:latest

echo "== 3. seed（幂等，可重复执行）"
docker exec zhiyin-fastapi python scripts/seed.py
docker exec zhiyin-fastapi python scripts/seed_demo.py

echo "== 4. nginx（infra-nginx 容器统一反代）"
sudo cp conf/nginx/zhiyin.conf /opt/infra/conf/nginx/zhiyin.conf
docker exec infra-nginx nginx -t
docker exec infra-nginx nginx -s reload

echo "== 5. healthz"
sleep 3
curl -s http://127.0.0.1:8014/healthz
echo
