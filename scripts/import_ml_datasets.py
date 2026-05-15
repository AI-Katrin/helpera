import argparse
import csv
import json
import os
import re
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / 'datasets'
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'https://helpera.synthetic')

CSV_TABLES = {
    'helpera_synthetic_volunteers.csv': 'ml_source_volunteers',
    'helpera_synthetic_ngos.csv': 'ml_source_ngos',
    'helpera_synthetic_tasks.csv': 'ml_source_tasks',
    'helpera_synthetic_events.csv': 'ml_source_events',
    'helpera_ranking_dataset.csv': 'ml_ranking_examples',
    'helpera_label_rules.csv': 'ml_label_rules',
}

INT_FIELDS = {
    'age', 'availability_hours_week', 'active_tasks_count', 'avg_response_time_hours',
    'is_duplicate_candidate', 'capacity', 'current_applications', 'label_signed',
    'label_relevance', 'skill_overlap_count', 'direction_overlap', 'format_match',
    'city_match', 'task_description_len', 'task_age_days', 'days_to_deadline',
    'task_is_new', 'task_is_duplicate_candidate', 'volunteer_active_tasks_count',
    'volunteer_availability_hours_week', 'ngo_avg_response_time_hours',
    'ngo_response_penalty', 'cold_start_volunteer', 'cold_start_task',
    'exploration_slot', 'clicked', 'details_viewed', 'applied', 'accepted',
    'completed', 'hidden', 'dwell_ms',
}

NUMERIC_FIELDS = {
    'profile_completeness', 'volunteer_reliability_score', 'volunteer_cancel_rate',
    'ngo_reliability_score', 'complaint_rate', 'task_quality_score', 'ngo_rating',
    'volunteer_rating', 'skill_jaccard', 'skill_coverage', 'embedding_cosine_sim',
    'task_urgency_score', 'application_pressure', 'volunteer_profile_completeness',
    'ngo_complaint_rate', 'scroll_depth_pct', 'task_popularity_score',
}

ML_SOURCE_TASK_FIELDS = {
    'task_id', 'ngo_id', 'title', 'description', 'requirements_raw', 'skills_raw',
    'skills_clean', 'directions_raw', 'directions_clean', 'format_raw', 'format_clean',
    'city_raw', 'city_clean', 'deadline', 'created_at', 'updated_at',
    'publication_status', 'task_quality_score', 'is_duplicate_candidate',
    'capacity', 'current_applications',
}


def load_config():
    for name in ('.env.local', '.env'):
        path = ROOT / name
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"\''))

    cfg = ROOT / 'js' / 'supabase-config.js'
    if cfg.exists():
        text = cfg.read_text(encoding='utf-8')
        if match := re.search(r"url:\s*['\"]([^'\"]+)['\"]", text):
            os.environ.setdefault('SUPABASE_URL', match.group(1))
        if match := re.search(r"anonKey:\s*['\"]([^'\"]+)['\"]", text):
            os.environ.setdefault('SUPABASE_ANON_KEY', match.group(1))

    return os.environ.get('SUPABASE_URL'), os.environ.get('SUPABASE_ANON_KEY')


def coerce(row):
    clean = {}
    for key, value in row.items():
        key = key.lstrip('\ufeff')
        value = None if value == '' else value
        if value is not None and key == 'payload_json':
            value = json.loads(value)
        elif value is not None and key in INT_FIELDS:
            value = int(float(value))
        elif value is not None and key in NUMERIC_FIELDS:
            value = float(value)
        clean[key] = value
    return clean


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return [coerce(row) for row in csv.DictReader(handle)]


def split_list(value):
    return [
        item.strip()
        for item in re.split(r'[|,]', str(value or ''))
        if item.strip()
    ]


def clean_text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def parse_date(value):
    value = clean_text(value)
    if not value:
        return None
    match = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4})', value)
    if match:
        day, month, year = match.groups()
        return f'{year}-{month}-{day}'
    return value[:10]


def parse_bullets(value):
    items = []
    for line in str(value or '').splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'^[-•]\s*', '', line).strip()
        line = line.rstrip(';').strip()
        if line:
            items.append(line)
    return items


CONTACT_FIRST_NAMES = [
    'Анна', 'Мария', 'Екатерина', 'Алина', 'Дарья', 'Елена', 'Ольга',
    'Ирина', 'Софья', 'Полина', 'Максим', 'Алексей', 'Иван', 'Дмитрий',
]

CONTACT_LAST_NAMES = [
    'Соколова', 'Петрова', 'Кузнецова', 'Фомина', 'Мартынова', 'Орлова',
    'Волкова', 'Лебедева', 'Егорова', 'Романова', 'Смирнов', 'Морозов',
    'Никитин', 'Беляев',
]


def short_org_name(name):
    name = clean_text(name)
    quoted = re.search(r'«([^»]+)»', name)
    if quoted:
        return quoted.group(1)
    return re.sub(
        r'^(АНО|НКО|Благотворительный фонд|Волонт[её]рский центр|'
        r'Образовательный центр|Социальная инициатива|Социальный проект)\s+',
        '',
        name,
        flags=re.IGNORECASE,
    ).strip() or name


def index_task_directions(tasks):
    result = {}
    for task in tasks:
        ngo_id = task.get('ngo_id')
        if not ngo_id:
            continue
        directions = split_list(task.get('direction_work') or task.get('directions_clean'))
        result.setdefault(ngo_id, [])
        for direction in directions:
            if direction not in result[ngo_id]:
                result[ngo_id].append(direction)
    return result


def synthetic_uuid(kind, source_id):
    return str(uuid.uuid5(UUID_NAMESPACE, f'{kind}:{source_id}'))


def birth_date_from_age(age, created_at):
    if not age:
        return None
    year = int(str(created_at or '2026')[:4] or 2026) - int(age)
    return f'{year}-01-01'


def volunteer_display_name(volunteer_id):
    try:
        index = int(str(volunteer_id).split('_')[-1])
    except ValueError:
        index = 0
    first_names = [
        'Анна', 'Мария', 'Екатерина', 'Алина', 'Дарья', 'Елена', 'Ольга',
        'Ирина', 'Софья', 'Полина', 'Максим', 'Алексей', 'Иван', 'Дмитрий',
        'Николай', 'Сергей', 'Юлия', 'Виктория', 'Олег', 'Артём'
    ]
    last_names = [
        'Соколова', 'Петрова', 'Кузнецова', 'Фомина', 'Мартынова', 'Орлова',
        'Волкова', 'Лебедева', 'Егорова', 'Романова', 'Смирнов', 'Морозов',
        'Никитин', 'Беляев', 'Кравцова', 'Павлова', 'Иванова', 'Михайлова',
        'Громов', 'Зайцева'
    ]
    return first_names[index % len(first_names)], last_names[(index * 7) % len(last_names)]


def task_description(item):
    return clean_text(item.get('about_task') or item.get('description'))


def task_start_date(item):
    return parse_date(item.get('date_start') or item.get('created_at'))


def task_end_date(item):
    return parse_date(item.get('date_end') or item.get('deadline'))


def normalize_ml_source_task(item):
    normalized = {key: item.get(key) for key in ML_SOURCE_TASK_FIELDS}
    normalized.update({
        'description': task_description(item),
        'skills_raw': item.get('skills_raw') or item.get('useful_skills'),
        'skills_clean': item.get('skills_clean') or item.get('useful_skills'),
        'directions_raw': item.get('directions_raw') or item.get('direction_work'),
        'directions_clean': item.get('directions_clean') or item.get('direction_work'),
        'format_raw': item.get('format_raw') or item.get('participation_type'),
        'format_clean': item.get('format_clean') or item.get('participation_type'),
        'city_raw': item.get('city_raw') or item.get('region'),
        'city_clean': item.get('city_clean') or item.get('region'),
        'deadline': task_end_date(item),
        'created_at': parse_date(item.get('created_at')) or task_start_date(item),
        'updated_at': parse_date(item.get('updated_at')) or parse_date(item.get('created_at')) or task_start_date(item),
    })
    return {key: normalized.get(key) for key in ML_SOURCE_TASK_FIELDS}


def post_rows(base_url, api_key, table, rows):
    if not rows:
        return
    url = f'{base_url}/rest/v1/{table}'
    body = json.dumps(rows, ensure_ascii=False).encode('utf-8')
    headers = {
        'apikey': api_key,
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates',
    }
    try:
        with urlopen(Request(url, data=body, headers=headers, method='POST'), timeout=120) as response:
            response.read()
    except HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Failed to import {table}: HTTP {error.code}: {detail[:800]}') from error


def import_csv(base_url, api_key, path, table, batch_size):
    total = 0
    batch = []
    with path.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            item = coerce(row)
            if table == 'ml_source_tasks':
                item = normalize_ml_source_task(item)
            if table == 'ml_ranking_examples':
                item['dataset_source'] = 'synthetic_final'
            batch.append(item)
            if len(batch) >= batch_size:
                post_rows(base_url, api_key, table, batch)
                total += len(batch)
                batch = []
    post_rows(base_url, api_key, table, batch)
    total += len(batch)
    print(f'{table}: {total} rows')


def import_platform_volunteers(base_url, api_key, data_dir, batch_size):
    rows = []
    for item in read_csv(data_dir / 'helpera_synthetic_volunteers.csv'):
        volunteer_id = item['volunteer_id']
        first_name, last_name = volunteer_display_name(volunteer_id)
        skills = split_list(item.get('skills') or item.get('skills_clean'))
        directions = split_list(item.get('help_directions') or item.get('directions_clean'))
        preferred_tasks = split_list(item.get('preferred_tasks') or item.get('help_directions') or item.get('directions_clean'))
        languages = split_list(item.get('communication_languages'))
        contact = f'{volunteer_id}@helpera.synthetic'
        rows.append({
            'id': synthetic_uuid('volunteer', volunteer_id),
            'contact': contact,
            'account': {'contact': contact, 'syntheticId': volunteer_id},
            'about': {
                'firstName': first_name,
                'lastName': last_name,
                'name': f'{first_name} {last_name}',
                'city': item.get('city') or item.get('city_clean'),
                'cityRaw': item.get('city_raw'),
                'country': item.get('country') or 'Россия',
                'birthDate': birth_date_from_age(item.get('age'), item.get('created_at')),
                'bio': clean_text(item.get('about_me')),
                'phone': f'+7 901 {int(volunteer_id.split("_")[-1]) // 100:03d}-{int(volunteer_id.split("_")[-1]) % 100:02d}-{(int(volunteer_id.split("_")[-1]) * 3) % 100:02d}',
            },
            'skills': {
                'skills': skills,
                'helpDirections': directions,
                'experience': item.get('experience_level')
            },
            'interests': {
                'tasks': preferred_tasks,
                'format': item.get('task_format') or item.get('format_clean'),
                'workload': item.get('availability'),
                'availabilityHoursWeek': item.get('availability_hours_week'),
                'languages': languages
            },
            'notifications': {'newTasks': True, 'statusUpdates': True, 'emailDigest': False},
            'registration_step': 'completed',
            'created_at': item.get('created_at'),
        })

    for start in range(0, len(rows), batch_size):
        post_rows(base_url, api_key, 'volunteer_profiles', rows[start:start + batch_size])
    print(f'volunteer_profiles: {len(rows)} rows')


def import_platform_ngos(base_url, api_key, data_dir, batch_size):
    rows = []
    task_directions = index_task_directions(read_csv(data_dir / 'helpera_synthetic_tasks.csv'))
    for index, item in enumerate(read_csv(data_dir / 'helpera_synthetic_ngos.csv')):
        ngo_id = item['ngo_id']
        contact = f'{ngo_id}@helpera.synthetic'
        org_name = clean_text(item.get('ngo_name'))
        short_name = short_org_name(org_name)
        org_type = clean_text(item.get('org_type'))
        city = clean_text(item.get('ngo_city_clean'))
        activity = ', '.join(task_directions.get(ngo_id, [])[:3]) or org_type
        first_name = CONTACT_FIRST_NAMES[index % len(CONTACT_FIRST_NAMES)]
        last_name = CONTACT_LAST_NAMES[index % len(CONTACT_LAST_NAMES)]
        rows.append({
            'id': synthetic_uuid('ngo', ngo_id),
            'org_name': org_name,
            'contact': contact,
            'account': {'orgName': org_name, 'contact': contact, 'syntheticId': ngo_id},
            'about': {
                'shortName': short_name,
                'orgType': org_type,
                'legalForm': org_type,
                'country': 'Россия',
                'city': city,
                'cityRaw': item.get('ngo_city_raw'),
                'activity': activity,
                'description': (
                    f'{org_name} работает в городе {city} и развивает проекты в направлении: {activity}. '
                    'Команда привлекает волонтёров к практическим задачам и помогает участникам '
                    'включиться в работу с понятными ожиданиями и поддержкой координатора.'
                ),
                'site': f'https://{ngo_id}.helpera.synthetic',
            },
            'contacts': {
                'firstName': first_name,
                'lastName': last_name,
                'position': 'Координатор волонтёров',
                'phone': f'+7 900 {index // 100:03d}-{index % 100:02d}-{(index * 7) % 100:02d}',
                'email': contact,
                'preferredMethod': 'Email',
                'comment': 'Свяжемся после отклика и уточним детали участия.',
                'notifications': {'email': True, 'phone': False},
            },
            'first_task': {},
            'registration_step': 'completed',
        })

    for start in range(0, len(rows), batch_size):
        post_rows(base_url, api_key, 'ngo_profiles', rows[start:start + batch_size])
    print(f'ngo_profiles: {len(rows)} rows')


def import_platform_tasks(base_url, api_key, data_dir, batch_size):
    rows = []
    for item in read_csv(data_dir / 'helpera_synthetic_tasks.csv'):
        task_id = item['task_id']
        start_date = task_start_date(item)
        end_date = task_end_date(item)
        description = task_description(item)
        action_items = parse_bullets(item.get('work_to_do'))
        directions = item.get('direction_work') or item.get('directions_clean')
        city = item.get('region') or item.get('city_clean')
        format_value = item.get('participation_type') or item.get('format_clean')
        skills = item.get('useful_skills') or item.get('skills_clean')
        rows.append({
            'id': synthetic_uuid('task', task_id),
            'ngo_profile_id': synthetic_uuid('ngo', item.get('ngo_id')),
            'title': clean_text(item.get('title')),
            'description': description,
            'format': format_value,
            'skills': skills,
            'date_start': start_date,
            'date_end': end_date,
            'status': item.get('publication_status') or 'published',
            'payload': {
                'syntheticId': task_id,
                'sourceNgoId': item.get('ngo_id'),
                'ngoName': item.get('ngo_name'),
                'requirements': item.get('requirements_raw'),
                'skills': skills,
                'directions': directions,
                'format': format_value,
                'city': city,
                'dateStart': start_date,
                'dateEnd': end_date,
                'actionItems': action_items,
                'workToDo': action_items,
                'expectedResult': 'Понятный, применимый итог, который команда сможет использовать, и краткая передача результата координатору.',
                'participationType': item.get('participation_type'),
                'capacity': item.get('capacity'),
                'currentApplications': item.get('current_applications'),
            },
            'created_at': parse_date(item.get('created_at')) or start_date,
            'updated_at': parse_date(item.get('updated_at')) or parse_date(item.get('created_at')) or start_date,
        })

    for start in range(0, len(rows), batch_size):
        post_rows(base_url, api_key, 'tasks', rows[start:start + batch_size])
    print(f'tasks: {len(rows)} rows')


def import_platform_events(base_url, api_key, data_dir, batch_size):
    rows = []
    for item in read_csv(data_dir / 'helpera_synthetic_events.csv'):
        rows.append({
            'event_id': item.get('event_id'),
            'timestamp': item.get('timestamp'),
            'volunteer_id': synthetic_uuid('volunteer', item.get('volunteer_id')),
            'task_id': synthetic_uuid('task', item.get('task_id')),
            'ngo_id': synthetic_uuid('ngo', item.get('ngo_id')),
            'event_type': item.get('event_type'),
            'status_from': item.get('status_from'),
            'status_to': item.get('status_to'),
            'dwell_ms': item.get('dwell_ms'),
            'scroll_depth_pct': item.get('scroll_depth_pct'),
            'reason': item.get('reason'),
            'payload_json': {
                **(item.get('payload_json') or {}),
                'sourceVolunteerId': item.get('volunteer_id'),
                'sourceTaskId': item.get('task_id'),
                'sourceNgoId': item.get('ngo_id'),
                'synthetic': True,
            },
        })

    for start in range(0, len(rows), batch_size):
        post_rows(base_url, api_key, 'ml_events', rows[start:start + batch_size])
    print(f'ml_events: {len(rows)} rows')


def import_platform_data(base_url, api_key, data_dir, batch_size):
    import_platform_ngos(base_url, api_key, data_dir, batch_size)
    import_platform_volunteers(base_url, api_key, data_dir, batch_size)
    import_platform_tasks(base_url, api_key, data_dir, batch_size)


def import_groups(base_url, api_key, data_dir):
    path = data_dir / 'helpera_lgbm_groups.txt'
    if not path.exists():
        return
    rows = [
        {'dataset_source': 'synthetic_final', 'qid': str(index), 'group_size': int(line.strip())}
        for index, line in enumerate(path.read_text(encoding='utf-8').splitlines())
        if line.strip()
    ]
    post_rows(base_url, api_key, 'ml_lgbm_groups', rows)
    print(f'ml_lgbm_groups: {len(rows)} rows')


def main():
    parser = argparse.ArgumentParser(description='Import Helpera ML CSV datasets into Supabase.')
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR))
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--skip-platform', action='store_true', help='Do not import synthetic rows into product tables.')
    parser.add_argument('--skip-ml', action='store_true', help='Do not import ML source/ranking tables.')
    args = parser.parse_args()

    base_url, api_key = load_config()
    if not base_url or not api_key:
        raise SystemExit('SUPABASE_URL/SUPABASE_ANON_KEY not found in env or js/supabase-config.js')

    data_dir = Path(args.data_dir)
    if not args.skip_platform:
        import_platform_data(base_url, api_key, data_dir, args.batch_size)

    if not args.skip_ml:
        for filename, table in CSV_TABLES.items():
            path = data_dir / filename
            if path.exists():
                import_csv(base_url, api_key, path, table, args.batch_size)
        import_platform_events(base_url, api_key, data_dir, args.batch_size)
        import_groups(base_url, api_key, data_dir)


if __name__ == '__main__':
    main()
