insert into public.ngo_profiles (
  id,
  org_name,
  contact,
  account,
  about,
  contacts,
  registration_step
) values
(
  '11111111-1111-4111-8111-111111111111',
  'АНО «Открытые знания»',
  'hello@open-knowledge.test',
  '{"orgName":"АНО «Открытые знания»","contact":"hello@open-knowledge.test"}'::jsonb,
  '{"shortName":"Открытые знания","orgType":"education","activity":"Образовательные программы для подростков и взрослых","country":"Россия","city":"Москва","description":"Помогаем людям получать прикладные знания и развивать цифровые навыки.","site":"https://open-knowledge.test"}'::jsonb,
  '{"firstName":"Анна","lastName":"Соколова","position":"Координатор волонтёров","phone":"+7 900 100-10-10","email":"hello@open-knowledge.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  '22222222-2222-4222-8222-222222222222',
  'Фонд «Шаг вперёд»',
  'team@step-forward.test',
  '{"orgName":"Фонд «Шаг вперёд»","contact":"team@step-forward.test"}'::jsonb,
  '{"shortName":"Шаг вперёд","orgType":"foundation","activity":"Социальная поддержка семей и подростков","country":"Россия","city":"Санкт-Петербург","description":"Поддерживаем семьи в трудной жизненной ситуации и запускаем наставнические проекты."}'::jsonb,
  '{"firstName":"Илья","lastName":"Кравцов","position":"Руководитель проектов","phone":"+7 900 200-20-20","email":"team@step-forward.test","preferredMethod":"phone"}'::jsonb,
  'completed'
),
(
  '33333333-3333-4333-8333-333333333333',
  'Фонд «Тёплый дом»',
  'info@warm-home.test',
  '{"orgName":"Фонд «Тёплый дом»","contact":"info@warm-home.test"}'::jsonb,
  '{"shortName":"Тёплый дом","orgType":"foundation","activity":"Помощь пожилым людям","country":"Россия","city":"Казань","description":"Организуем бытовую, информационную и эмоциональную поддержку пожилых людей."}'::jsonb,
  '{"firstName":"Мария","lastName":"Никитина","position":"PR-менеджер","phone":"+7 900 300-30-30","email":"info@warm-home.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  '44444444-4444-4444-8444-444444444444',
  'Центр «Город рядом»',
  'contact@gorod-ryadom.test',
  '{"orgName":"Центр «Город рядом»","contact":"contact@gorod-ryadom.test"}'::jsonb,
  '{"shortName":"Город рядом","orgType":"community","activity":"Городские и соседские инициативы","country":"Россия","city":"Екатеринбург","description":"Развиваем локальные сообщества и помогаем жителям запускать полезные инициативы."}'::jsonb,
  '{"firstName":"Олег","lastName":"Беляев","position":"Координатор сообщества","phone":"+7 900 400-40-40","email":"contact@gorod-ryadom.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  '55555555-5555-4555-8555-555555555555',
  'Проект «Чистый берег»',
  'volunteers@clean-shore.test',
  '{"orgName":"Проект «Чистый берег»","contact":"volunteers@clean-shore.test"}'::jsonb,
  '{"shortName":"Чистый берег","orgType":"initiative","activity":"Экологические акции и просвещение","country":"Россия","city":"Нижний Новгород","description":"Проводим уборки берегов, лекции и кампании по ответственному потреблению."}'::jsonb,
  '{"firstName":"Дарья","lastName":"Ким","position":"Координатор акций","phone":"+7 900 500-50-50","email":"volunteers@clean-shore.test","preferredMethod":"phone"}'::jsonb,
  'completed'
),
(
  '66666666-6666-4666-8666-666666666666',
  'АНО «Культура рядом»',
  'hello@culture-near.test',
  '{"orgName":"АНО «Культура рядом»","contact":"hello@culture-near.test"}'::jsonb,
  '{"shortName":"Культура рядом","orgType":"culture","activity":"Доступные культурные события","country":"Россия","city":"Пермь","description":"Делаем культурные события понятными и доступными для разных аудиторий."}'::jsonb,
  '{"firstName":"Елена","lastName":"Орлова","position":"Продюсер программ","phone":"+7 900 600-60-60","email":"hello@culture-near.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  '77777777-7777-4777-8777-777777777777',
  'Фонд «Вместе детям»',
  'kids@together.test',
  '{"orgName":"Фонд «Вместе детям»","contact":"kids@together.test"}'::jsonb,
  '{"shortName":"Вместе детям","orgType":"foundation","activity":"Поддержка детей и семей","country":"Россия","city":"Новосибирск","description":"Помогаем детям раскрывать способности через наставничество, события и образовательные программы."}'::jsonb,
  '{"firstName":"Светлана","lastName":"Романова","position":"Специалист по программам","phone":"+7 900 700-70-70","email":"kids@together.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  '88888888-8888-4888-8888-888888888888',
  'Центр «Точка опоры»',
  'support@opora.test',
  '{"orgName":"Центр «Точка опоры»","contact":"support@opora.test"}'::jsonb,
  '{"shortName":"Точка опоры","orgType":"social_center","activity":"Психологическая и информационная поддержка","country":"Россия","city":"Самара","description":"Помогаем людям находить поддержку, ресурсы и понятные маршруты помощи."}'::jsonb,
  '{"firstName":"Николай","lastName":"Громов","position":"Координатор помощи","phone":"+7 900 800-80-80","email":"support@opora.test","preferredMethod":"phone"}'::jsonb,
  'completed'
),
(
  '99999999-9999-4999-8999-999999999999',
  'Лаборатория «Добрые данные»',
  'data@good-data.test',
  '{"orgName":"Лаборатория «Добрые данные»","contact":"data@good-data.test"}'::jsonb,
  '{"shortName":"Добрые данные","orgType":"research","activity":"Аналитика для социальных проектов","country":"Россия","city":"Москва","description":"Помогаем НКО работать с данными, оценивать результаты и принимать решения."}'::jsonb,
  '{"firstName":"Кирилл","lastName":"Мартынов","position":"Аналитик","phone":"+7 900 900-90-90","email":"data@good-data.test","preferredMethod":"email"}'::jsonb,
  'completed'
),
(
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'Сообщество «Равные возможности»',
  'hello@equal.test',
  '{"orgName":"Сообщество «Равные возможности»","contact":"hello@equal.test"}'::jsonb,
  '{"shortName":"Равные возможности","orgType":"community","activity":"Инклюзивные проекты","country":"Россия","city":"Ростов-на-Дону","description":"Создаём инклюзивные события и образовательные материалы для широкой аудитории."}'::jsonb,
  '{"firstName":"Алина","lastName":"Фомина","position":"Менеджер проектов","phone":"+7 901 000-00-00","email":"hello@equal.test","preferredMethod":"email"}'::jsonb,
  'completed'
)
on conflict (id) do update set
  org_name = excluded.org_name,
  contact = excluded.contact,
  account = excluded.account,
  about = excluded.about,
  contacts = excluded.contacts,
  registration_step = excluded.registration_step;

insert into public.volunteer_profiles (
  id,
  contact,
  account,
  about,
  skills,
  interests,
  notifications,
  registration_step
) values
(
  'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  'ekaterina@example.test',
  '{"contact":"ekaterina@example.test"}'::jsonb,
  '{"name":"Екатерина Тарабрина","city":"Москва","about":"Люблю структурировать информацию и помогать образовательным проектам."}'::jsonb,
  '{"skills":["Аналитика","SMM","Работа с документами"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Образование","Социальные проекты"],"format":"Онлайн","workload":"2–4 часа в неделю","languages":["Русский","Английский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":false}'::jsonb,
  'completed'
),
(
  'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  'alex.petrov@example.test',
  '{"contact":"alex.petrov@example.test"}'::jsonb,
  '{"name":"Александр Петров","city":"Санкт-Петербург","about":"Дизайнер, готов помогать с презентациями, афишами и визуальными материалами."}'::jsonb,
  '{"skills":["Дизайн","Фото и видео","Презентации"],"experience":"Продвинутый уровень"}'::jsonb,
  '{"tasks":["Культура","Образование"],"format":"Онлайн","workload":"Разовые задачи","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":true}'::jsonb,
  'completed'
),
(
  'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
  'maria.smirnova@example.test',
  '{"contact":"maria.smirnova@example.test"}'::jsonb,
  '{"name":"Мария Смирнова","city":"Казань","about":"Помогаю с коммуникациями, текстами и ведением социальных сетей."}'::jsonb,
  '{"skills":["SMM","Копирайтинг","Коммуникация"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Помощь пожилым людям","Социальные проекты"],"format":"Смешанный","workload":"4–6 часов в неделю","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":false}'::jsonb,
  'completed'
),
(
  'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
  'ivan.kuznetsov@example.test',
  '{"contact":"ivan.kuznetsov@example.test"}'::jsonb,
  '{"name":"Иван Кузнецов","city":"Екатеринбург","about":"Хорошо организую процессы, люблю события и работу с людьми."}'::jsonb,
  '{"skills":["Организация мероприятий","Координация волонтёров","Коммуникация"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Городские инициативы","Культура"],"format":"Оффлайн","workload":"Выходные","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":false,"emailDigest":false}'::jsonb,
  'completed'
),
(
  'ffffffff-ffff-4fff-8fff-ffffffffffff',
  'daria.kim@example.test',
  '{"contact":"daria.kim@example.test"}'::jsonb,
  '{"name":"Дарья Ким","city":"Нижний Новгород","about":"Интересуюсь экологией и готова помогать в полевых акциях."}'::jsonb,
  '{"skills":["Организация мероприятий","Фото и видео","Коммуникация"],"experience":"Начинающий"}'::jsonb,
  '{"tasks":["Экология"],"format":"Оффлайн","workload":"Разовые задачи","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":true}'::jsonb,
  'completed'
),
(
  '12121212-1212-4121-8121-121212121212',
  'elena.orlova@example.test',
  '{"contact":"elena.orlova@example.test"}'::jsonb,
  '{"name":"Елена Орлова","city":"Пермь","about":"Переводчик и редактор, люблю культурные и образовательные проекты."}'::jsonb,
  '{"skills":["Переводы","Копирайтинг","Работа с документами"],"experience":"Продвинутый уровень"}'::jsonb,
  '{"tasks":["Культура","Образование"],"format":"Онлайн","workload":"2–4 часа в неделю","languages":["Русский","Английский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":true}'::jsonb,
  'completed'
),
(
  '13131313-1313-4131-8131-131313131313',
  'nikolay.gromov@example.test',
  '{"contact":"nikolay.gromov@example.test"}'::jsonb,
  '{"name":"Николай Громов","city":"Самара","about":"Есть опыт наставничества и индивидуальной поддержки."}'::jsonb,
  '{"skills":["Наставничество","Работа с детьми","Коммуникация"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Помощь детям","Социальные проекты"],"format":"Смешанный","workload":"4–6 часов в неделю","languages":["Русский"]}'::jsonb,
  '{"newTasks":false,"statusUpdates":true,"emailDigest":false}'::jsonb,
  'completed'
),
(
  '14141414-1414-4141-8141-141414141414',
  'kirill.martynov@example.test',
  '{"contact":"kirill.martynov@example.test"}'::jsonb,
  '{"name":"Кирилл Мартынов","city":"Москва","about":"Аналитик данных, могу помогать с отчётами, таблицами и исследованиями."}'::jsonb,
  '{"skills":["Аналитика","Исследования","Работа с документами"],"experience":"Продвинутый уровень"}'::jsonb,
  '{"tasks":["Аналитика","Образование"],"format":"Онлайн","workload":"Проектная занятость","languages":["Русский","Английский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":false}'::jsonb,
  'completed'
),
(
  '15151515-1515-4151-8151-151515151515',
  'alina.fomina@example.test',
  '{"contact":"alina.fomina@example.test"}'::jsonb,
  '{"name":"Алина Фомина","city":"Ростов-на-Дону","about":"Помогаю делать материалы доступными и понятными для разных аудиторий."}'::jsonb,
  '{"skills":["Инклюзия","Копирайтинг","Дизайн"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Инклюзия","Культура"],"format":"Онлайн","workload":"2–4 часа в неделю","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":true,"emailDigest":true}'::jsonb,
  'completed'
),
(
  '16161616-1616-4161-8161-161616161616',
  'sergey.ivanov@example.test',
  '{"contact":"sergey.ivanov@example.test"}'::jsonb,
  '{"name":"Сергей Иванов","city":"Новосибирск","about":"Люблю технические задачи, таблицы, автоматизацию и аккуратную документацию."}'::jsonb,
  '{"skills":["Работа с документами","Аналитика","Автоматизация"],"experience":"Есть опыт"}'::jsonb,
  '{"tasks":["Социальные проекты","Аналитика"],"format":"Онлайн","workload":"Разовые задачи","languages":["Русский"]}'::jsonb,
  '{"newTasks":true,"statusUpdates":false,"emailDigest":true}'::jsonb,
  'completed'
)
on conflict (id) do update set
  contact = excluded.contact,
  account = excluded.account,
  about = excluded.about,
  skills = excluded.skills,
  interests = excluded.interests,
  notifications = excluded.notifications,
  registration_step = excluded.registration_step;

insert into public.tasks (
  id,
  ngo_profile_id,
  title,
  description,
  format,
  skills,
  date_start,
  date_end,
  status,
  payload
) values
(
  '20111111-1111-4111-8111-111111111111',
  '11111111-1111-4111-8111-111111111111',
  'Анализ обратной связи участников образовательной программы',
  'Нужно собрать ответы участников, разложить их по темам и подготовить краткий отчёт с выводами.',
  'Онлайн',
  'Аналитика, Работа с документами, Исследования',
  current_date + 3,
  current_date + 14,
  'published',
  '{"title":"Анализ обратной связи участников образовательной программы","description":"Нужно собрать ответы участников, разложить их по темам и подготовить краткий отчёт с выводами.","format":"Онлайн","skills":"Аналитика, Работа с документами, Исследования","dateStart":"2026-05-02","dateEnd":"2026-05-13","comment":"Подойдёт тем, кто любит таблицы и аккуратные выводы.","taskAgreement":true}'::jsonb
),
(
  '20222222-2222-4222-8222-222222222222',
  '22222222-2222-4222-8222-222222222222',
  'Подготовка аналитического отчёта по социальному проекту',
  'Помочь команде оформить данные проекта в понятный отчёт для партнёров.',
  'Онлайн',
  'Аналитика, Копирайтинг, Работа с документами',
  current_date + 2,
  current_date + 12,
  'published',
  '{"title":"Подготовка аналитического отчёта по социальному проекту","description":"Помочь команде оформить данные проекта в понятный отчёт для партнёров.","format":"Онлайн","skills":"Аналитика, Копирайтинг, Работа с документами","dateStart":"2026-05-01","dateEnd":"2026-05-11","comment":"Нужно будет работать с таблицей и текстовым шаблоном.","taskAgreement":true}'::jsonb
),
(
  '20333333-3333-4333-8333-333333333333',
  '33333333-3333-4333-8333-333333333333',
  'Помощь в ведении социальных сетей НКО',
  'Подготовить контент-план на две недели и несколько коротких постов для социальных сетей.',
  'Онлайн',
  'SMM, Копирайтинг, Дизайн',
  current_date + 4,
  current_date + 18,
  'published',
  '{"title":"Помощь в ведении социальных сетей НКО","description":"Подготовить контент-план на две недели и несколько коротких постов для социальных сетей.","format":"Онлайн","skills":"SMM, Копирайтинг, Дизайн","dateStart":"2026-05-03","dateEnd":"2026-05-17","comment":"Можно предложить свои идеи рубрик.","taskAgreement":true}'::jsonb
),
(
  '20444444-4444-4444-8444-444444444444',
  '44444444-4444-4444-8444-444444444444',
  'Координация волонтёров на городском событии',
  'Помочь с регистрацией участников, навигацией и коммуникацией команды на площадке.',
  'Оффлайн',
  'Организация мероприятий, Координация волонтёров, Коммуникация',
  current_date + 7,
  current_date + 7,
  'published',
  '{"title":"Координация волонтёров на городском событии","description":"Помочь с регистрацией участников, навигацией и коммуникацией команды на площадке.","format":"Оффлайн","skills":"Организация мероприятий, Координация волонтёров, Коммуникация","dateStart":"2026-05-06","dateEnd":"2026-05-06","comment":"Занятость около 5 часов в день события.","taskAgreement":true}'::jsonb
),
(
  '20555555-5555-4555-8555-555555555555',
  '55555555-5555-4555-8555-555555555555',
  'Фотоотчёт с экологической акции',
  'Сделать фотографии на акции и отобрать 20–30 кадров для публикации.',
  'Оффлайн',
  'Фото и видео, Коммуникация',
  current_date + 10,
  current_date + 10,
  'published',
  '{"title":"Фотоотчёт с экологической акции","description":"Сделать фотографии на акции и отобрать 20–30 кадров для публикации.","format":"Оффлайн","skills":"Фото и видео, Коммуникация","dateStart":"2026-05-09","dateEnd":"2026-05-09","comment":"Подойдёт камера или хороший смартфон.","taskAgreement":true}'::jsonb
),
(
  '20666666-6666-4666-8666-666666666666',
  '66666666-6666-4666-8666-666666666666',
  'Перевод описаний культурных событий',
  'Перевести короткие описания событий на английский язык и вычитать тексты.',
  'Онлайн',
  'Переводы, Копирайтинг, Работа с документами',
  current_date + 5,
  current_date + 16,
  'published',
  '{"title":"Перевод описаний культурных событий","description":"Перевести короткие описания событий на английский язык и вычитать тексты.","format":"Онлайн","skills":"Переводы, Копирайтинг, Работа с документами","dateStart":"2026-05-04","dateEnd":"2026-05-15","comment":"Всего около 8 небольших текстов.","taskAgreement":true}'::jsonb
),
(
  '20777777-7777-4777-8777-777777777777',
  '77777777-7777-4777-8777-777777777777',
  'Наставничество для подростков в образовательной программе',
  'Провести несколько онлайн-встреч с подростком и помочь ему спланировать учебный проект.',
  'Смешанный',
  'Наставничество, Работа с детьми, Коммуникация',
  current_date + 8,
  current_date + 35,
  'published',
  '{"title":"Наставничество для подростков в образовательной программе","description":"Провести несколько онлайн-встреч с подростком и помочь ему спланировать учебный проект.","format":"Смешанный","skills":"Наставничество, Работа с детьми, Коммуникация","dateStart":"2026-05-07","dateEnd":"2026-06-03","comment":"Потребуется 1 встреча в неделю.","taskAgreement":true}'::jsonb
),
(
  '20888888-8888-4888-8888-888888888888',
  '88888888-8888-4888-8888-888888888888',
  'Подготовка справочника ресурсов помощи',
  'Собрать и структурировать список полезных организаций, телефонов и сервисов поддержки.',
  'Онлайн',
  'Исследования, Работа с документами, Аналитика',
  current_date + 6,
  current_date + 20,
  'published',
  '{"title":"Подготовка справочника ресурсов помощи","description":"Собрать и структурировать список полезных организаций, телефонов и сервисов поддержки.","format":"Онлайн","skills":"Исследования, Работа с документами, Аналитика","dateStart":"2026-05-05","dateEnd":"2026-05-19","comment":"Итог нужен в виде таблицы.","taskAgreement":true}'::jsonb
),
(
  '20999999-9999-4999-8999-999999999999',
  '99999999-9999-4999-8999-999999999999',
  'Визуализация данных для отчёта НКО',
  'Помочь превратить таблицы и цифры в понятные диаграммы для годового отчёта.',
  'Онлайн',
  'Аналитика, Дизайн, Презентации',
  current_date + 9,
  current_date + 21,
  'published',
  '{"title":"Визуализация данных для отчёта НКО","description":"Помочь превратить таблицы и цифры в понятные диаграммы для годового отчёта.","format":"Онлайн","skills":"Аналитика, Дизайн, Презентации","dateStart":"2026-05-08","dateEnd":"2026-05-20","comment":"Можно работать в Google Sheets, Excel или Figma.","taskAgreement":true}'::jsonb
),
(
  '20aaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  'Адаптация материалов для инклюзивного события',
  'Проверить тексты и презентацию события на понятность, доступность и корректную терминологию.',
  'Онлайн',
  'Инклюзия, Копирайтинг, Дизайн',
  current_date + 4,
  current_date + 15,
  'published',
  '{"title":"Адаптация материалов для инклюзивного события","description":"Проверить тексты и презентацию события на понятность, доступность и корректную терминологию.","format":"Онлайн","skills":"Инклюзия, Копирайтинг, Дизайн","dateStart":"2026-05-03","dateEnd":"2026-05-14","comment":"Будет полезен опыт в доступной коммуникации.","taskAgreement":true}'::jsonb
)
on conflict (id) do update set
  ngo_profile_id = excluded.ngo_profile_id,
  title = excluded.title,
  description = excluded.description,
  format = excluded.format,
  skills = excluded.skills,
  date_start = excluded.date_start,
  date_end = excluded.date_end,
  status = excluded.status,
  payload = excluded.payload;
