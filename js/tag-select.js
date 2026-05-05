/**
 * TagSelect — multi-select dropdown with autocomplete and custom entry.
 *
 * Usage:
 *   const ts = TagSelect({ inputEl, toggleEl, dropdownEl, chipsEl, hiddenEl, options });
 *   ts.setValue('Value 1, Value 2');  // populate from saved data
 *   ts.getValue();                    // read comma-separated string
 */
function TagSelect({ inputEl, toggleEl, dropdownEl, chipsEl, hiddenEl, options }) {
  const values = new Set();

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c])
    );
  }

  function sync() {
    hiddenEl.value = Array.from(values).join(', ');
    hiddenEl.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function close() {
    dropdownEl.classList.remove('visible');
    inputEl.closest('.autocomplete').classList.remove('open');
  }

  function renderDropdown(showAll) {
    const q = inputEl.value.trim().toLowerCase();
    dropdownEl.innerHTML = '';

    if (!q && !showAll) { close(); return; }

    const matches = options.filter(o =>
      (showAll || o.toLowerCase().includes(q)) && !values.has(o)
    );

    const raw = inputEl.value.trim();
    if (
      !showAll && raw &&
      !options.some(o => o.toLowerCase() === raw.toLowerCase()) &&
      !values.has(raw)
    ) {
      matches.unshift({ label: `Добавить «${raw}»`, value: raw });
    }

    if (!matches.length) { close(); return; }

    matches.forEach(item => {
      const val   = typeof item === 'string' ? item : item.value;
      const label = typeof item === 'string' ? item : item.label;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'suggestion-item';
      btn.textContent = label;
      btn.addEventListener('mousedown', e => {
        e.preventDefault();
        addValue(val);
      });
      dropdownEl.appendChild(btn);
    });

    dropdownEl.classList.add('visible');
    inputEl.closest('.autocomplete').classList.add('open');
  }

  function addValue(val) {
    const v = val.trim();
    if (!v || values.has(v)) return;
    values.add(v);

    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip active skill-chip';
    chip.innerHTML = `<span>${esc(v)}</span><span class="skill-remove" aria-hidden="true">×</span>`;
    chip.querySelector('.skill-remove').addEventListener('click', ev => {
      ev.stopPropagation();
      values.delete(v);
      chip.remove();
      sync();
    });
    chipsEl.appendChild(chip);
    inputEl.value = '';
    close();
    sync();
  }

  /* --- Event wiring --- */
  inputEl.addEventListener('input',  () => renderDropdown(false));
  inputEl.addEventListener('focus',  () => { if (inputEl.value.trim()) renderDropdown(false); });
  inputEl.addEventListener('blur',   () => setTimeout(close, 150));
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); if (inputEl.value.trim()) addValue(inputEl.value); }
    if (e.key === 'Escape') close();
  });
  toggleEl.addEventListener('click', () => {
    if (dropdownEl.classList.contains('visible') && !inputEl.value.trim()) close();
    else { inputEl.focus(); renderDropdown(true); }
  });

  /* --- Public API --- */
  return {
    addValue,
    setValue(csv) {
      values.clear();
      chipsEl.innerHTML = '';
      String(csv || '').split(',').map(s => s.trim()).filter(Boolean).forEach(addValue);
    },
    getValue() { return hiddenEl.value; }
  };
}
