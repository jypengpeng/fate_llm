#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$#" -ne 2 ]; then
    echo -e "${RED}用法: sudo $0 <域名> <端口>${NC}"
    echo -e "${YELLOW}示例: sudo $0 llmapi.yukido.xyz 3000${NC}"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请用 sudo 运行此脚本${NC}"
    exit 1
fi

DOMAIN=$1
PORT=$2

if ! echo "$PORT" | grep -qE '^[0-9]+$'; then
    echo -e "${RED}端口必须是数字${NC}"
    exit 1
fi

CONF_NAME=$(echo "$DOMAIN" | cut -d'.' -f1)

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  HTTPS 反向代理一键配置${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  域名:   ${YELLOW}${DOMAIN}${NC}"
echo -e "  端口:   ${YELLOW}${PORT}${NC}"
echo -e "  配置名: ${YELLOW}${CONF_NAME}${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 1. 检查依赖
echo -e "${YELLOW}[1/6] 检查并安装依赖...${NC}"

if ! command -v nginx > /dev/null 2>&1; then
    echo "  安装 nginx..."
    apt update -qq
    apt install -y nginx > /dev/null 2>&1
    systemctl start nginx
    systemctl enable nginx
    echo -e "  ${GREEN}nginx 安装完成${NC}"
else
    echo -e "  ${GREEN}nginx 已安装${NC}"
fi

if ! command -v certbot > /dev/null 2>&1; then
    echo "  安装 certbot..."
    apt install -y certbot python3-certbot-nginx > /dev/null 2>&1
    echo -e "  ${GREEN}certbot 安装完成${NC}"
else
    echo -e "  ${GREEN}certbot 已安装${NC}"
fi

# 2. DNS 检查
echo -e "${YELLOW}[2/6] 检查 DNS 解析...${NC}"

RESOLVED_IP=$(dig +short "$DOMAIN" | head -n1)
SERVER_IP=$(curl -s ifconfig.me)

if [ -z "$RESOLVED_IP" ]; then
    echo -e "  ${RED}✗ ${DOMAIN} 无法解析${NC}"
    echo -e "  ${RED}  请先在 Cloudflare 添加 A 记录指向 ${SERVER_IP}${NC}"
    exit 1
fi

if [ "$RESOLVED_IP" != "$SERVER_IP" ]; then
    echo -e "  ${YELLOW}⚠ DNS 解析 IP (${RESOLVED_IP}) 与本机 IP (${SERVER_IP}) 不一致${NC}"
    echo -e "  ${YELLOW}  如果开了 Cloudflare 代理（橙色云朵），这是正常的${NC}"
    read -p "  是否继续？(y/n) " -n 1 -r
    echo
    if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
        exit 1
    fi
else
    echo -e "  ${GREEN}✓ DNS 解析正确 → ${RESOLVED_IP}${NC}"
fi

# 3. 检查端口
echo -e "${YELLOW}[3/6] 检查端口 ${PORT} 是否有服务运行...${NC}"

if ss -tlnp | grep -q ":${PORT} "; then
    echo -e "  ${GREEN}✓ 端口 ${PORT} 有服务在运行${NC}"
else
    echo -e "  ${YELLOW}⚠ 端口 ${PORT} 没有检测到服务${NC}"
    read -p "  是否继续？(y/n) " -n 1 -r
    echo
    if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
        exit 1
    fi
fi

# 4. 配置 Nginx
echo -e "${YELLOW}[4/6] 配置 Nginx 反向代理...${NC}"

CONF_PATH="/etc/nginx/sites-available/${CONF_NAME}.conf"
LINK_PATH="/etc/nginx/sites-enabled/${CONF_NAME}.conf"

if [ -f "$CONF_PATH" ]; then
    echo -e "  ${YELLOW}⚠ 配置文件 ${CONF_PATH} 已存在${NC}"
    read -p "  是否覆盖？(y/n) " -n 1 -r
    echo
    if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
        exit 1
    fi
fi

cat > "$CONF_PATH" <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf "$CONF_PATH" "$LINK_PATH"
rm -f /etc/nginx/sites-enabled/default

if nginx -t 2>&1; then
    systemctl reload nginx
    echo -e "  ${GREEN}✓ Nginx 配置完成${NC}"
else
    echo -e "  ${RED}✗ Nginx 配置有误${NC}"
    rm -f "$CONF_PATH" "$LINK_PATH"
    exit 1
fi

# 5. 申请 SSL 证书
echo -e "${YELLOW}[5/6] 申请 SSL 证书...${NC}"

if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect; then
    echo -e "  ${GREEN}✓ SSL 证书申请成功${NC}"
else
    echo -e "  ${RED}✗ SSL 证书申请失败${NC}"
    echo -e "  ${RED}  请确认：${NC}"
    echo -e "  ${RED}  1. DNS 已生效${NC}"
    echo -e "  ${RED}  2. Cloudflare 为灰色云朵${NC}"
    echo -e "  ${RED}  3. 80 端口可从外部访问${NC}"
    exit 1
fi

# 6. 防火墙
echo -e "${YELLOW}[6/6] 配置防火墙...${NC}"

if command -v ufw > /dev/null 2>&1; then
    ufw allow 22/tcp  > /dev/null 2>&1
    ufw allow 80/tcp  > /dev/null 2>&1
    ufw allow 443/tcp > /dev/null 2>&1
    ufw deny "$PORT"  > /dev/null 2>&1
    echo "y" | ufw enable > /dev/null 2>&1
    echo -e "  ${GREEN}✓ 防火墙已配置（端口 ${PORT} 已封闭）${NC}"
else
    echo -e "  ${YELLOW}⚠ 未检测到 ufw，请手动封闭端口 ${PORT}${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✅ 全部完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  HTTPS 访问: ${GREEN}https://${DOMAIN}${NC}"
echo -e "  HTTP  自动跳转 HTTPS"
echo -e "  端口 ${PORT} 已禁止外部直接访问"
echo -e "${GREEN}========================================${NC}"
