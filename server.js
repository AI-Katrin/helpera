const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT_DIR = __dirname;

loadEnvFile('.env.local');
loadEnvFile('.env');

const PORT = Number(process.env.PORT || 3000);

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

function loadEnvFile(fileName) {
  const filePath = path.join(ROOT_DIR, fileName);
  if (!fs.existsSync(filePath)) return;

  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    const separatorIndex = trimmed.indexOf('=');
    if (separatorIndex === -1) return;

    const key = trimmed.slice(0, separatorIndex).trim();
    let value = trimmed.slice(separatorIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (key && !process.env[key]) process.env[key] = value;
  });
}

function sendJson(res, statusCode, body) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 64 * 1024) {
        reject(new Error('Слишком большой запрос'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error('Некорректный JSON'));
      }
    });
    req.on('error', reject);
  });
}

function taskPrompt(action, task, userPrompt = '', style = '') {
  const title = task.title || 'Название пока не заполнено';
  const description = task.description || 'Описание пока не заполнено';
  const skills = task.skills || 'Навыки пока не указаны';
  const format = task.format || 'Формат пока не указан';
  const directions = task.directions || 'Направление пока не указано';
  const comment = task.comment || 'Комментарий не указан';

  if (action === 'draft') {
    return [
      'Составь понятное описание волонтёрской задачи для платформы Helpera.',
      'Пиши на русском, дружелюбно и конкретно. Без markdown, списков и заголовков.',
      'В первую очередь учитывай уже заполненное поле «Описание задачи»: сохрани его факты, смысл и ограничения.',
      'Если описание уже заполнено, не начинай с нуля, а перепиши и улучши именно этот текст.',
      'Остальные поля используй как контекст для уточнения формулировок.',
      `Пожелание пользователя: ${userPrompt || 'нет'}`,
      `Стиль варианта: ${style || 'ясный и дружелюбный'}`,
      `Название: ${title}`,
      `Текущее описание: ${description}`,
      `Формат: ${format}`,
      `Навыки: ${skills}`,
      `Направление: ${directions}`,
      `Комментарий НКО: ${comment}`,
      'Текст должен быть 3-5 предложений и объяснять, что нужно сделать, какой результат ожидается и почему помощь важна.'
    ].join('\n');
  }

  return [
    'Улучши описание волонтёрской задачи для платформы Helpera.',
    'Сохрани смысл, не выдумывай факты, пиши на русском. Без markdown, списков и заголовков.',
    `Пожелание пользователя: ${userPrompt || 'нет'}`,
    `Стиль варианта: ${style || 'ясный и дружелюбный'}`,
    `Название: ${title}`,
    `Текущее описание: ${description}`,
    `Формат: ${format}`,
    `Навыки: ${skills}`,
    `Направление: ${directions}`,
    `Комментарий НКО: ${comment}`,
    'Сделай текст яснее, теплее и конкретнее. Длина 3-5 предложений.'
  ].join('\n');
}

function parseYandexText(data) {
  if (typeof data.output_text === 'string') return data.output_text;
  const output = Array.isArray(data.output) ? data.output : [];
  return output
    .flatMap((item) => Array.isArray(item.content) ? item.content : [])
    .map((content) => content.text || '')
    .join('')
    .trim();
}

function resolveYandexModel(folder) {
  const model = process.env.YANDEX_CLOUD_MODEL || 'yandexgpt-lite/latest';
  if (model.startsWith('gpt://')) return model.replaceAll('YANDEX_CLOUD_FOLDER', folder || '');
  return `gpt://${folder}/${model}`;
}

function clampNumber(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(number, max));
}

async function handleAiTask(req, res) {
  const apiKey = process.env.YANDEX_CLOUD_API_KEY;
  const folder = process.env.YANDEX_CLOUD_FOLDER;
  const model = resolveYandexModel(folder);

  if (!apiKey || !folder) {
    sendJson(res, 500, { error: 'Не заданы YANDEX_CLOUD_API_KEY и YANDEX_CLOUD_FOLDER в .env.local' });
    return;
  }

  try {
    const body = await readJson(req);
    const action = body.action === 'draft' ? 'draft' : 'transform';
    const options = body.options || {};
    const temperature = clampNumber(options.temperature, 0.3, 0, 1);
    const maxOutputTokens = Math.round(clampNumber(options.maxOutputTokens, 500, 150, 900));
    const userPrompt = String(body.prompt || '').slice(0, 500);
    const style = String(options.style || '').slice(0, 300);
    const prompt = taskPrompt(action, body.task || {}, userPrompt, style);
    const aiResponse = await fetch('https://ai.api.cloud.yandex.net/v1/responses', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
        'OpenAI-Project': folder
      },
      body: JSON.stringify({
        model,
        temperature,
        instructions: 'Ты помогаешь НКО формулировать задачи для волонтёров. Отвечай только готовым текстом для поля описания.',
        input: prompt,
        max_output_tokens: maxOutputTokens
      })
    });
    const data = await aiResponse.json().catch(() => ({}));
    if (!aiResponse.ok) {
      sendJson(res, aiResponse.status, { error: data.error?.message || 'Yandex AI вернул ошибку' });
      return;
    }

    const text = parseYandexText(data);
    if (!text) {
      sendJson(res, 502, { error: 'Yandex AI вернул пустой ответ' });
      return;
    }
    sendJson(res, 200, { text });
  } catch (error) {
    sendJson(res, 500, { error: error.message || 'Не удалось обратиться к AI' });
  }
}

function serveStatic(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const requestedPath = url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname);
  const filePath = path.normalize(path.join(ROOT_DIR, requestedPath));

  if (!filePath.startsWith(ROOT_DIR) || path.basename(filePath).startsWith('.')) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (error, content) => {
    if (error) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
}

const server = http.createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/api/ai/task') {
    handleAiTask(req, res);
    return;
  }
  if (req.method === 'GET') {
    serveStatic(req, res);
    return;
  }
  res.writeHead(405);
  res.end('Method not allowed');
});

server.listen(PORT, () => {
  console.log(`Helpera is running at http://localhost:${PORT}`);
  console.log(`YANDEX_CLOUD_FOLDER: ${process.env.YANDEX_CLOUD_FOLDER ? 'set' : 'missing'}`);
  console.log(`YANDEX_CLOUD_API_KEY: ${process.env.YANDEX_CLOUD_API_KEY ? 'set' : 'missing'}`);
  console.log(`YANDEX_CLOUD_MODEL: ${process.env.YANDEX_CLOUD_MODEL || 'yandexgpt-lite/latest'}`);
});
