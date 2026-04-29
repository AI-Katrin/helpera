# Helpera static site

CSS вынесен из HTML в папку `css/pages/`.

У каждой страницы свой CSS-файл. Так безопаснее: в макетах есть одинаковые классы `.content`, `.layout`, `.panel`, `.badge`, но на разных страницах они имеют разные размеры и сетки. Если склеить всё в один общий файл, страницы начнут конфликтовать.

Открывай `index.html` через Live Server в VS Code или публикуй папку на GitHub Pages.

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
