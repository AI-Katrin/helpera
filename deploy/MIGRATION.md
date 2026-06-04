# Миграция с Railway на reg.ru

## Что переносится

| Компонент | Где |
|-----------|-----|
| Python-сервер (`server.py`) | VPS reg.ru |
| Статика (HTML/CSS/JS) | Отдаётся тем же Python-сервером |
| ML-модели (`model_artifacts/`) | VPS reg.ru |
| База данных | **Остаётся на Supabase** (ничего не меняется) |
| Домен `helpera.ru` | Перенаправить DNS на IP сервера reg.ru |

---

## Шаг 1 — Заказать VPS на reg.ru

- **Тариф**: минимум 2 vCPU / **4 GB RAM** (sentence-transformers требует ~1 GB)
- **ОС**: Ubuntu 22.04 LTS
- Сохранить IP-адрес сервера

---

## Шаг 2 — Первичная настройка сервера

```bash
# Подключиться по SSH
ssh root@<IP_СЕРВЕРА>

# Загрузить скрипт и nginx-конфиг
scp deploy/setup.sh deploy/nginx.conf root@<IP_СЕРВЕРА>:/tmp/

# Запустить установку
bash /tmp/setup.sh
```

---

## Шаг 3 — Создать файл с переменными окружения

На сервере создать `/var/www/helpera/.env`:

```bash
cp deploy/.env.example /var/www/helpera/.env
nano /var/www/helpera/.env   # заполнить все значения
chmod 600 /var/www/helpera/.env
chown helpera:helpera /var/www/helpera/.env
```

---

## Шаг 4 — Залить код и установить зависимости

В `deploy/deploy.sh` заменить `SERVER_IP` на реальный IP сервера, затем:

```bash
chmod +x deploy/deploy.sh
bash deploy/deploy.sh --first
```

Это:
1. Синхронизирует файлы через rsync
2. Создаёт Python venv и устанавливает зависимости
3. Регистрирует и запускает systemd-сервис

---

## Шаг 5 — Настроить DNS

В панели reg.ru (или у регистратора домена) изменить A-запись:

```
helpera.ru.     A   <IP_СЕРВЕРА>
www.helpera.ru. A   <IP_СЕРВЕРА>
```

DNS обновляется до 24 часов.

---

## Шаг 6 — Получить SSL-сертификат

После обновления DNS:

```bash
ssh root@<IP_СЕРВЕРА>
certbot --nginx -d helpera.ru -d www.helpera.ru
```

Certbot сам обновит nginx-конфиг и настроит авторобновление сертификата.

---

## Шаг 7 — Отключить Railway

После проверки что сайт работает на новом сервере:
- Удалить сервис в Railway или остановить его

---

## Полезные команды на сервере

```bash
# Статус приложения
systemctl status helpera

# Логи в реальном времени
journalctl -u helpera -f

# Перезапуск после изменений
systemctl restart helpera

# Проверка nginx
nginx -t && systemctl reload nginx
```

---

## Обновление кода в будущем

```bash
# С локальной машины
bash deploy/deploy.sh
```
