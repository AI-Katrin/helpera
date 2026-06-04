#!/bin/bash
# Скрипт первичной настройки сервера reg.ru (Ubuntu 22.04)
# Запускать от root: bash setup.sh

set -e

echo "=== 1. Обновление системы ==="
apt-get update && apt-get upgrade -y

echo "=== 2. Установка зависимостей системы ==="
apt-get install -y python3.11 python3.11-venv python3-pip nginx git certbot python3-certbot-nginx curl ufw

echo "=== 3. Настройка файрвола ==="
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "=== 4. Создание пользователя helpera ==="
if ! id -u helpera &>/dev/null; then
    useradd -r -s /bin/bash -d /var/www/helpera helpera
fi

echo "=== 5. Создание директории проекта ==="
mkdir -p /var/www/helpera
chown helpera:helpera /var/www/helpera

echo "=== 6. Настройка nginx ==="
cp /tmp/nginx.conf /etc/nginx/sites-available/helpera
ln -sf /etc/nginx/sites-available/helpera /etc/nginx/sites-enabled/helpera
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== Готово. Следующий шаг: загрузить файлы проекта (см. deploy.sh) ==="
