const RUSSIAN_CITIES = [
  'Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань',
  'Нижний Новгород', 'Челябинск', 'Самара', 'Уфа', 'Ростов-на-Дону',
  'Омск', 'Красноярск', 'Воронеж', 'Пермь', 'Волгоград',
  'Краснодар', 'Саратов', 'Тюмень', 'Тольятти', 'Ижевск',
  'Барнаул', 'Ульяновск', 'Иркутск', 'Хабаровск', 'Ярославль',
  'Владивосток', 'Махачкала', 'Томск', 'Оренбург', 'Кемерово',
  'Новокузнецк', 'Рязань', 'Астрахань', 'Набережные Челны', 'Пенза',
  'Липецк', 'Тула', 'Киров', 'Чебоксары', 'Калининград',
  'Брянск', 'Иваново', 'Магнитогорск', 'Курск', 'Тверь',
  'Нижний Тагил', 'Ставрополь', 'Симферополь', 'Белгород', 'Архангельск',
  'Владимир', 'Сочи', 'Смоленск', 'Сургут', 'Чита',
  'Якутск', 'Улан-Удэ', 'Мурманск', 'Вологда', 'Саранск',
  'Череповец', 'Тамбов', 'Калуга', 'Стерлитамак', 'Грозный',
  'Нальчик', 'Орел', 'Владикавказ', 'Кострома', 'Нижневартовск',
  'Новороссийск', 'Йошкар-Ола', 'Петрозаводск', 'Дзержинск', 'Сыктывкар',
  'Нижнекамск', 'Абакан', 'Благовещенск', 'Ангарск', 'Рыбинск',
  'Псков', 'Балашиха', 'Химки', 'Подольск', 'Красногорск',
  'Мытищи', 'Люберцы', 'Электросталь', 'Коломна', 'Одинцово',
  'Серпухов', 'Щёлково', 'Жуковский', 'Реутов', 'Пушкино',
];

/**
 * CitySelect — single-select dropdown with arrow toggle and autocomplete.
 * Mirrors the TagSelect pattern but for a single value (fills input, no chips).
 *
 * Usage:
 *   CitySelect({ inputEl, toggleEl, dropdownEl });
 */
function CitySelect({ inputEl, toggleEl, dropdownEl }) {
  function close() {
    dropdownEl.classList.remove('visible');
    inputEl.closest('.autocomplete').classList.remove('open');
  }

  function renderDropdown(showAll) {
    const q = inputEl.value.trim().toLowerCase();
    dropdownEl.innerHTML = '';

    if (!q && !showAll) { close(); return; }

    const matches = RUSSIAN_CITIES.filter(c =>
      showAll || c.toLowerCase().includes(q)
    );

    if (!matches.length) { close(); return; }

    matches.forEach(city => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'suggestion-item';
      btn.textContent = city;
      btn.addEventListener('mousedown', e => {
        e.preventDefault();
        inputEl.value = city;
        inputEl.dispatchEvent(new Event('input', { bubbles: true }));
        inputEl.dispatchEvent(new Event('change', { bubbles: true }));
        close();
      });
      dropdownEl.appendChild(btn);
    });

    dropdownEl.classList.add('visible');
    inputEl.closest('.autocomplete').classList.add('open');
  }

  inputEl.addEventListener('input',  () => renderDropdown(false));
  inputEl.addEventListener('focus',  () => { if (inputEl.value.trim()) renderDropdown(false); });
  inputEl.addEventListener('blur',   () => setTimeout(close, 150));
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowDown') {
      const first = dropdownEl.querySelector('.suggestion-item');
      if (first) { e.preventDefault(); first.focus(); }
    }
  });
  dropdownEl.addEventListener('keydown', e => {
    if (e.key === 'Escape') { close(); inputEl.focus(); }
  });
  toggleEl.addEventListener('click', () => {
    if (dropdownEl.classList.contains('visible') && !inputEl.value.trim()) close();
    else { inputEl.focus(); renderDropdown(true); }
  });
}
