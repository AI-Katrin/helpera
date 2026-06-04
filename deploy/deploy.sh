#!/bin/bash
# Скрипт деплоя / обновления на сервере
# Запускать от root или helpera с sudo: bash deploy.sh
# Первый запуск: bash deploy.sh --first

set -e

APP_DIR=/var/www/helpera
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)   # корень проекта на локальной машине

FIRST_RUN=false
[[ "$1" == "--first" ]] && FIRST_RUN=true

echo "=== Синхронизация файлов ==="
rsync -az --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='venv' \
    --exclude='node_modules' \
    "$REPO_DIR/" helpera@SERVER_IP:"$APP_DIR/"

if $FIRST_RUN; then
    echo "=== Создание виртуального окружения ==="
    ssh helpera@SERVER_IP "
        cd $APP_DIR &&
        python3.11 -m venv venv &&
        venv/bin/pip install --upgrade pip &&
        venv/bin/pip install -r requirements.txt
    "

    echo "=== Установка systemd-сервиса ==="
    ssh root@SERVER_IP "
        cp $APP_DIR/deploy/helpera.service /etc/systemd/system/helpera.service &&
        systemctl daemon-reload &&
        systemctl enable helpera &&
        systemctl start helpera
    "
else
    echo "=== Перезапуск сервиса ==="
    ssh root@SERVER_IP "
        cd $APP_DIR &&
        venv/bin/pip install -r requirements.txt --quiet &&
        systemctl restart helpera
    "
fi

echo "=== Статус сервиса ==="
ssh root@SERVER_IP "systemctl status helpera --no-pager"

echo "=== Деплой завершён ==="
