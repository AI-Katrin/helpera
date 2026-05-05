# Helpera static site

CSS вынесен из HTML в папку `css/pages/`.

У каждой страницы свой CSS-файл. Так безопаснее: в макетах есть одинаковые классы `.content`, `.layout`, `.panel`, `.badge`, но на разных страницах они имеют разные размеры и сетки. Если склеить всё в один общий файл, страницы начнут конфликтовать.

Открывай `index.html` через Live Server в VS Code или публикуй папку на GitHub Pages.

## Yandex AI Studio

AI-помощник на `ngo-task-create.html` работает через локальный backend-прокси, чтобы ключ Yandex Cloud не попадал в браузер и репозиторий.

1. Скопируй `.env.example` в `.env.local`.
2. Заполни в `.env.local` значения:

```env
YANDEX_CLOUD_FOLDER=
YANDEX_CLOUD_API_KEY=
YANDEX_CLOUD_MODEL="yandexgpt-lite/latest"
```

3. Запусти сайт через Python:

```bash
python3 server.py
```

Если в проекте установлен Node.js 18+, можно запустить и через Node:

```bash
node server.js
```

4. Открой `http://localhost:3000/ngo-task-create.html`.

`.env.local` добавлен в `.gitignore`, поэтому секреты не должны попасть в GitHub. На GitHub Pages этот AI endpoint работать не сможет, потому что Pages не умеет хранить серверные секреты.

## Supabase

1. Создай проект в Supabase.
2. Открой SQL Editor и выполни содержимое `supabase-schema.sql`.
3. Для тестовых данных выполни содержимое `supabase-seed.sql`.
4. Вставь значения проекта в `js/supabase-config.js`:

```js
window.HELPERA_SUPABASE = {
  url: 'https://YOUR_PROJECT.supabase.co',
  anonKey: 'YOUR_PUBLIC_ANON_KEY'
};
```

После этого страницы регистрации НКО и волонтёра, создание задачи, каталог задач и отклики будут работать через Supabase. Если ключи пустые, проект продолжит работать через `localStorage` для локальной проверки.
