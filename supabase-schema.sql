create extension if not exists pgcrypto;

create table if not exists public.volunteer_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  contact text not null,
  account jsonb not null default '{}'::jsonb,
  about jsonb not null default '{}'::jsonb,
  skills jsonb not null default '{}'::jsonb,
  interests jsonb not null default '{}'::jsonb,
  notifications jsonb not null default '{}'::jsonb,
  registration_step text not null default 'account',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ngo_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  org_name text not null,
  contact text not null,
  account jsonb not null default '{}'::jsonb,
  about jsonb not null default '{}'::jsonb,
  contacts jsonb not null default '{}'::jsonb,
  first_task jsonb not null default '{}'::jsonb,
  registration_step text not null default 'account',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  ngo_profile_id uuid references public.ngo_profiles(id) on delete cascade,
  title text not null,
  description text not null,
  format text,
  skills text,
  date_start date,
  date_end date,
  status text not null default 'published',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.applications (
  id uuid primary key default gen_random_uuid(),
  task_id uuid references public.tasks(id) on delete cascade,
  volunteer_profile_id uuid references public.volunteer_profiles(id) on delete set null,
  message text,
  format text,
  status text not null default 'review',
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.app_events (
  id uuid primary key default gen_random_uuid(),
  event_type text not null,
  actor_role text,
  actor_profile_id uuid,
  application_id uuid references public.applications(id) on delete cascade,
  task_id uuid references public.tasks(id) on delete cascade,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.volunteer_profiles add column if not exists city_raw text;
alter table public.volunteer_profiles add column if not exists city_clean text;
alter table public.volunteer_profiles add column if not exists format_raw text;
alter table public.volunteer_profiles add column if not exists format_clean text;
alter table public.volunteer_profiles add column if not exists skills_raw text;
alter table public.volunteer_profiles add column if not exists skills_clean text;
alter table public.volunteer_profiles add column if not exists directions_raw text;
alter table public.volunteer_profiles add column if not exists directions_clean text;
alter table public.volunteer_profiles add column if not exists experience_raw text;
alter table public.volunteer_profiles add column if not exists experience_level text;
alter table public.volunteer_profiles add column if not exists age integer;
alter table public.volunteer_profiles add column if not exists availability_hours_week integer;
alter table public.volunteer_profiles add column if not exists profile_completeness numeric(5,3) not null default 0;
alter table public.volunteer_profiles add column if not exists volunteer_reliability_score numeric(5,3) not null default 0.5;
alter table public.volunteer_profiles add column if not exists volunteer_cancel_rate numeric(5,3) not null default 0;
alter table public.volunteer_profiles add column if not exists active_tasks_count integer not null default 0;

alter table public.ngo_profiles add column if not exists ngo_city_raw text;
alter table public.ngo_profiles add column if not exists ngo_city_clean text;
alter table public.ngo_profiles add column if not exists org_type text;
alter table public.ngo_profiles add column if not exists avg_response_time_hours integer not null default 24;
alter table public.ngo_profiles add column if not exists ngo_reliability_score numeric(5,3) not null default 0.5;
alter table public.ngo_profiles add column if not exists complaint_rate numeric(5,3) not null default 0;
alter table public.ngo_profiles add column if not exists active_tasks_count integer not null default 0;

alter table public.tasks add column if not exists requirements_raw text;
alter table public.tasks add column if not exists skills_raw text;
alter table public.tasks add column if not exists skills_clean text;
alter table public.tasks add column if not exists directions_raw text;
alter table public.tasks add column if not exists directions_clean text;
alter table public.tasks add column if not exists format_raw text;
alter table public.tasks add column if not exists format_clean text;
alter table public.tasks add column if not exists city_raw text;
alter table public.tasks add column if not exists city_clean text;
alter table public.tasks add column if not exists deadline date;
alter table public.tasks add column if not exists publication_status text not null default 'published';
alter table public.tasks add column if not exists task_quality_score numeric(5,3) not null default 0;
alter table public.tasks add column if not exists is_duplicate_candidate integer not null default 0;
alter table public.tasks add column if not exists capacity integer not null default 1;
alter table public.tasks add column if not exists current_applications integer not null default 0;

create table if not exists public.ml_events (
  event_id text primary key,
  "timestamp" timestamptz not null default now(),
  volunteer_id text,
  task_id text,
  ngo_id text,
  event_type text not null,
  status_from text,
  status_to text,
  dwell_ms numeric,
  scroll_depth_pct numeric,
  reason text,
  payload_json jsonb not null default '{}'::jsonb,
  app_event_id uuid references public.app_events(id) on delete cascade,
  application_id uuid references public.applications(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.ml_ranking_examples (
  volunteer_id text not null,
  task_id text not null,
  ngo_id text,
  qid text not null,
  interaction_status text not null,
  label_signed integer not null,
  label_relevance integer not null,
  ngo_rating numeric,
  volunteer_rating numeric,
  volunteer_skills_raw text,
  task_skills_raw text,
  volunteer_directions_raw text,
  task_directions_raw text,
  volunteer_format_raw text,
  task_format_raw text,
  volunteer_city_raw text,
  task_city_raw text,
  skill_overlap_count integer not null default 0,
  skill_jaccard numeric not null default 0,
  skill_coverage numeric not null default 0,
  direction_overlap integer not null default 0,
  format_match integer not null default 0,
  city_match integer not null default 0,
  embedding_cosine_sim numeric not null default 0,
  task_quality_score numeric not null default 0,
  task_description_len integer not null default 0,
  task_age_days integer not null default 0,
  days_to_deadline integer not null default 0,
  task_urgency_score numeric not null default 0,
  task_is_new integer not null default 0,
  task_is_duplicate_candidate integer not null default 0,
  capacity integer not null default 1,
  current_applications integer not null default 0,
  application_pressure numeric not null default 0,
  volunteer_reliability_score numeric not null default 0,
  volunteer_cancel_rate numeric not null default 0,
  volunteer_active_tasks_count integer not null default 0,
  volunteer_profile_completeness numeric not null default 0,
  volunteer_availability_hours_week integer not null default 0,
  ngo_reliability_score numeric not null default 0,
  ngo_avg_response_time_hours integer not null default 0,
  ngo_complaint_rate numeric not null default 0,
  ngo_response_penalty integer not null default 0,
  cold_start_volunteer integer not null default 0,
  cold_start_task integer not null default 0,
  exploration_slot integer not null default 0,
  clicked integer not null default 0,
  details_viewed integer not null default 0,
  applied integer not null default 0,
  accepted integer not null default 0,
  completed integer not null default 0,
  hidden integer not null default 0,
  dwell_ms integer not null default 0,
  scroll_depth_pct numeric not null default 0,
  task_popularity_score numeric not null default 0,
  dataset_source text not null default 'production',
  created_at timestamptz not null default now(),
  primary key (dataset_source, volunteer_id, task_id)
);

create table if not exists public.ml_label_rules (
  label_relevance integer primary key,
  label_signed integer not null,
  interaction_status text not null,
  meaning text not null
);

create table if not exists public.ml_lgbm_groups (
  dataset_source text not null,
  qid text not null,
  group_size integer not null,
  created_at timestamptz not null default now(),
  primary key (dataset_source, qid)
);

create table if not exists public.ml_source_volunteers (
  volunteer_id text primary key,
  city_raw text not null,
  city_clean text not null,
  format_raw text not null,
  format_clean text not null,
  skills_raw text not null,
  skills_clean text not null,
  directions_raw text not null,
  directions_clean text not null,
  experience_raw text not null,
  experience_level text not null,
  age integer not null,
  availability_hours_week integer not null,
  profile_completeness numeric not null,
  volunteer_reliability_score numeric not null,
  volunteer_cancel_rate numeric not null,
  active_tasks_count integer not null,
  created_at date not null
);

create table if not exists public.ml_source_ngos (
  ngo_id text primary key,
  ngo_name text not null,
  ngo_city_raw text not null,
  ngo_city_clean text not null,
  org_type text not null,
  avg_response_time_hours integer not null,
  ngo_reliability_score numeric not null,
  complaint_rate numeric not null,
  active_tasks_count integer not null
);

create table if not exists public.ml_source_tasks (
  task_id text primary key,
  ngo_id text not null,
  title text not null,
  description text not null,
  requirements_raw text not null,
  skills_raw text not null,
  skills_clean text not null,
  directions_raw text not null,
  directions_clean text not null,
  format_raw text not null,
  format_clean text not null,
  city_raw text not null,
  city_clean text not null,
  deadline date not null,
  created_at date not null,
  updated_at date not null,
  publication_status text not null,
  task_quality_score numeric not null,
  is_duplicate_candidate integer not null,
  capacity integer not null,
  current_applications integer not null
);

create table if not exists public.ml_source_events (
  event_id text primary key,
  "timestamp" timestamptz not null,
  volunteer_id text not null,
  task_id text not null,
  ngo_id text not null,
  event_type text not null,
  status_from text,
  status_to text,
  dwell_ms numeric,
  scroll_depth_pct numeric,
  reason text,
  payload_json jsonb not null default '{}'::jsonb
);

alter table public.volunteer_profiles add column if not exists user_id uuid references auth.users(id) on delete set null;
alter table public.ngo_profiles add column if not exists user_id uuid references auth.users(id) on delete set null;

create index if not exists volunteer_profiles_user_id_idx on public.volunteer_profiles(user_id);
create index if not exists ngo_profiles_user_id_idx on public.ngo_profiles(user_id);

create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create or replace function public.helpera_clean_text(value text)
returns text as $$
begin
  return nullif(regexp_replace(trim(coalesce(value, '')), '\s+', ' ', 'g'), '');
end;
$$ language plpgsql immutable;

create or replace function public.helpera_jsonb_text_list(value jsonb)
returns text as $$
declare
  result text;
begin
  if value is null then
    return '';
  end if;

  if jsonb_typeof(value) = 'array' then
    select string_agg(public.helpera_clean_text(item), ', ' order by ord)
    into result
    from jsonb_array_elements_text(value) with ordinality as items(item, ord)
    where public.helpera_clean_text(item) is not null;
    return coalesce(result, '');
  end if;

  if jsonb_typeof(value) = 'string' then
    return public.helpera_clean_text(value #>> '{}');
  end if;

  return '';
end;
$$ language plpgsql immutable;

create or replace function public.helpera_age_from_birth_date(value text)
returns integer as $$
declare
  birth_date date;
  years integer;
begin
  if value is null or trim(value) = '' then
    return null;
  end if;
  birth_date := value::date;
  years := date_part('year', age(current_date, birth_date));
  if years < 10 or years > 100 then
    return null;
  end if;
  return years;
exception when others then
  return null;
end;
$$ language plpgsql stable;

create or replace function public.helpera_profile_completeness(
  about_data jsonb,
  skills_data jsonb,
  interests_data jsonb
)
returns numeric as $$
declare
  filled integer := 0;
begin
  filled := filled + case when coalesce(about_data->>'firstName', '') <> '' then 1 else 0 end;
  filled := filled + case when coalesce(about_data->>'lastName', '') <> '' then 1 else 0 end;
  filled := filled + case when coalesce(about_data->>'city', '') <> '' then 1 else 0 end;
  filled := filled + case when coalesce(about_data->>'birthDate', '') <> '' then 1 else 0 end;
  filled := filled + case when coalesce(about_data->>'bio', '') <> '' then 1 else 0 end;
  filled := filled + case when public.helpera_jsonb_text_list(skills_data->'skills') <> '' then 1 else 0 end;
  filled := filled + case when public.helpera_jsonb_text_list(skills_data->'helpDirections') <> '' then 1 else 0 end;
  filled := filled + case when coalesce(interests_data->>'format', '') <> '' then 1 else 0 end;
  return round(filled::numeric / 8, 3);
end;
$$ language plpgsql immutable;

create or replace function public.sync_ml_event_from_app_event()
returns trigger as $$
declare
  app_row public.applications%rowtype;
  task_row public.tasks%rowtype;
  resolved_task_id uuid;
  resolved_volunteer_id text;
  resolved_ngo_id text;
begin
  if new.application_id is not null then
    select * into app_row from public.applications where id = new.application_id;
  end if;

  resolved_task_id := coalesce(new.task_id, app_row.task_id);
  if resolved_task_id is not null then
    select * into task_row from public.tasks where id = resolved_task_id;
  end if;

  resolved_volunteer_id := coalesce(
    new.payload->>'volunteer_id',
    case when new.actor_role = 'volunteer' then new.actor_profile_id::text end,
    app_row.volunteer_profile_id::text
  );
  resolved_ngo_id := coalesce(
    new.payload->>'ngo_id',
    case when new.actor_role = 'ngo' then new.actor_profile_id::text end,
    task_row.ngo_profile_id::text
  );

  insert into public.ml_events (
    event_id,
    "timestamp",
    volunteer_id,
    task_id,
    ngo_id,
    event_type,
    status_from,
    status_to,
    dwell_ms,
    scroll_depth_pct,
    reason,
    payload_json,
    app_event_id,
    application_id
  ) values (
    new.id::text,
    new.created_at,
    resolved_volunteer_id,
    resolved_task_id::text,
    resolved_ngo_id,
    new.event_type,
    coalesce(new.payload->>'status_from', new.payload->>'previous_status'),
    coalesce(new.payload->>'status_to', new.payload->>'status'),
    nullif(new.payload->>'dwell_ms', '')::numeric,
    coalesce(nullif(new.payload->>'scroll_depth_pct', '')::numeric, nullif(new.payload->>'scroll_depth', '')::numeric),
    new.payload->>'reason',
    new.payload,
    new.id,
    new.application_id
  )
  on conflict (event_id) do update set
    "timestamp" = excluded."timestamp",
    volunteer_id = excluded.volunteer_id,
    task_id = excluded.task_id,
    ngo_id = excluded.ngo_id,
    event_type = excluded.event_type,
    status_from = excluded.status_from,
    status_to = excluded.status_to,
    dwell_ms = excluded.dwell_ms,
    scroll_depth_pct = excluded.scroll_depth_pct,
    reason = excluded.reason,
    payload_json = excluded.payload_json,
    application_id = excluded.application_id;

  return new;
end;
$$ language plpgsql;

create or replace function public.sync_volunteer_ml_fields()
returns trigger as $$
begin
  new.city_raw := coalesce(new.city_raw, new.about->>'city');
  new.city_clean := coalesce(public.helpera_clean_text(new.city_clean), public.helpera_clean_text(new.about->>'city'));
  new.format_raw := coalesce(new.format_raw, new.interests->>'format');
  new.format_clean := coalesce(public.helpera_clean_text(new.format_clean), public.helpera_clean_text(new.interests->>'format'));
  new.skills_raw := coalesce(new.skills_raw, public.helpera_jsonb_text_list(new.skills->'skills'));
  new.skills_clean := coalesce(public.helpera_clean_text(new.skills_clean), public.helpera_jsonb_text_list(new.skills->'skills'));
  new.directions_raw := coalesce(new.directions_raw, public.helpera_jsonb_text_list(new.skills->'helpDirections'), public.helpera_jsonb_text_list(new.interests->'tasks'));
  new.directions_clean := coalesce(public.helpera_clean_text(new.directions_clean), public.helpera_jsonb_text_list(new.skills->'helpDirections'), public.helpera_jsonb_text_list(new.interests->'tasks'));
  new.experience_raw := coalesce(new.experience_raw, new.skills->>'experience');
  new.experience_level := coalesce(public.helpera_clean_text(new.experience_level), public.helpera_clean_text(new.skills->>'experience'));
  new.age := coalesce(new.age, public.helpera_age_from_birth_date(new.about->>'birthDate'));
  new.profile_completeness := public.helpera_profile_completeness(new.about, new.skills, new.interests);
  return new;
end;
$$ language plpgsql;

create or replace function public.sync_ngo_ml_fields()
returns trigger as $$
begin
  new.ngo_city_raw := coalesce(new.ngo_city_raw, new.about->>'city');
  new.ngo_city_clean := coalesce(public.helpera_clean_text(new.ngo_city_clean), public.helpera_clean_text(new.about->>'city'));
  new.org_type := coalesce(new.org_type, new.about->>'orgType');
  return new;
end;
$$ language plpgsql;

create or replace function public.sync_task_ml_fields()
returns trigger as $$
declare
  quality_parts integer := 0;
begin
  new.skills_raw := coalesce(new.skills_raw, new.skills, new.payload->>'skills');
  new.skills_clean := coalesce(public.helpera_clean_text(new.skills_clean), public.helpera_clean_text(new.skills), public.helpera_clean_text(new.payload->>'skills'));
  new.directions_raw := coalesce(new.directions_raw, new.payload->>'directions');
  new.directions_clean := coalesce(public.helpera_clean_text(new.directions_clean), public.helpera_clean_text(new.payload->>'directions'));
  new.format_raw := coalesce(new.format_raw, new.format, new.payload->>'format');
  new.format_clean := coalesce(public.helpera_clean_text(new.format_clean), public.helpera_clean_text(new.format), public.helpera_clean_text(new.payload->>'format'));
  new.city_raw := coalesce(new.city_raw, new.payload->>'city');
  new.city_clean := coalesce(public.helpera_clean_text(new.city_clean), public.helpera_clean_text(new.payload->>'city'));
  new.deadline := coalesce(new.deadline, new.date_end, nullif(new.payload->>'dateEnd', '')::date);
  new.publication_status := coalesce(new.publication_status, new.status, 'published');
  new.capacity := greatest(coalesce(new.capacity, nullif(new.payload->>'capacity', '')::integer, 1), 1);

  quality_parts := quality_parts + case when coalesce(new.title, '') <> '' then 1 else 0 end;
  quality_parts := quality_parts + case when length(coalesce(new.description, '')) >= 30 then 1 else 0 end;
  quality_parts := quality_parts + case when coalesce(new.skills_clean, '') <> '' then 1 else 0 end;
  quality_parts := quality_parts + case when coalesce(new.directions_clean, '') <> '' then 1 else 0 end;
  quality_parts := quality_parts + case when coalesce(new.format_clean, '') <> '' then 1 else 0 end;
  quality_parts := quality_parts + case when new.deadline is not null then 1 else 0 end;
  new.task_quality_score := round(quality_parts::numeric / 6, 3);

  return new;
exception when others then
  return new;
end;
$$ language plpgsql;

create or replace function public.refresh_ml_counters()
returns trigger as $$
declare
  affected_task_id uuid;
  affected_volunteer_id uuid;
  affected_ngo_id uuid;
begin
  if TG_OP = 'DELETE' then
    affected_task_id := old.task_id;
    affected_volunteer_id := old.volunteer_profile_id;
  else
    affected_task_id := new.task_id;
    affected_volunteer_id := new.volunteer_profile_id;
  end if;

  if affected_task_id is not null then
    update public.tasks
    set current_applications = (
      select count(*)::integer
      from public.applications
      where task_id = affected_task_id
        and status <> 'draft'
    )
    where id = affected_task_id
    returning ngo_profile_id into affected_ngo_id;
  end if;

  if affected_volunteer_id is not null then
    update public.volunteer_profiles
    set active_tasks_count = (
      select count(*)::integer
      from public.applications
      where volunteer_profile_id = affected_volunteer_id
        and status in ('review', 'invite', 'active')
    ),
    volunteer_cancel_rate = coalesce((
      select round(
        count(*) filter (where event_type = 'task_apply_cancelled')::numeric
        / nullif(count(*) filter (where event_type in ('application_submitted', 'task_apply_cancelled')), 0),
        3
      )
      from public.ml_events
      where volunteer_id = affected_volunteer_id::text
    ), volunteer_cancel_rate)
    where id = affected_volunteer_id;
  end if;

  if affected_ngo_id is not null then
    update public.ngo_profiles
    set active_tasks_count = (
      select count(*)::integer
      from public.tasks
      where ngo_profile_id = affected_ngo_id
        and status = 'published'
    )
    where id = affected_ngo_id;
  end if;

  if TG_OP = 'DELETE' then
    return old;
  end if;
  return new;
end;
$$ language plpgsql;

drop trigger if exists set_volunteer_profiles_updated_at on public.volunteer_profiles;
create trigger set_volunteer_profiles_updated_at
before update on public.volunteer_profiles
for each row execute function public.set_updated_at();

drop trigger if exists sync_volunteer_ml_fields on public.volunteer_profiles;
create trigger sync_volunteer_ml_fields
before insert or update on public.volunteer_profiles
for each row execute function public.sync_volunteer_ml_fields();

drop trigger if exists set_ngo_profiles_updated_at on public.ngo_profiles;
create trigger set_ngo_profiles_updated_at
before update on public.ngo_profiles
for each row execute function public.set_updated_at();

drop trigger if exists sync_ngo_ml_fields on public.ngo_profiles;
create trigger sync_ngo_ml_fields
before insert or update on public.ngo_profiles
for each row execute function public.sync_ngo_ml_fields();

drop trigger if exists set_tasks_updated_at on public.tasks;
create trigger set_tasks_updated_at
before update on public.tasks
for each row execute function public.set_updated_at();

drop trigger if exists sync_task_ml_fields on public.tasks;
create trigger sync_task_ml_fields
before insert or update on public.tasks
for each row execute function public.sync_task_ml_fields();

drop trigger if exists set_applications_updated_at on public.applications;
create trigger set_applications_updated_at
before update on public.applications
for each row execute function public.set_updated_at();

drop trigger if exists refresh_ml_counters_from_applications on public.applications;
create trigger refresh_ml_counters_from_applications
after insert or update or delete on public.applications
for each row execute function public.refresh_ml_counters();

drop trigger if exists sync_ml_event_from_app_event on public.app_events;
create trigger sync_ml_event_from_app_event
after insert or update on public.app_events
for each row execute function public.sync_ml_event_from_app_event();

create or replace view public.ml_volunteers as
select
  id::text as volunteer_id,
  coalesce(city_raw, about->>'city', '') as city_raw,
  coalesce(city_clean, public.helpera_clean_text(about->>'city'), '') as city_clean,
  coalesce(format_raw, interests->>'format', '') as format_raw,
  coalesce(format_clean, public.helpera_clean_text(interests->>'format'), '') as format_clean,
  coalesce(skills_raw, public.helpera_jsonb_text_list(skills->'skills'), '') as skills_raw,
  coalesce(skills_clean, public.helpera_jsonb_text_list(skills->'skills'), '') as skills_clean,
  coalesce(directions_raw, public.helpera_jsonb_text_list(skills->'helpDirections'), public.helpera_jsonb_text_list(interests->'tasks'), '') as directions_raw,
  coalesce(directions_clean, public.helpera_jsonb_text_list(skills->'helpDirections'), public.helpera_jsonb_text_list(interests->'tasks'), '') as directions_clean,
  coalesce(experience_raw, skills->>'experience', '') as experience_raw,
  coalesce(experience_level, skills->>'experience', '') as experience_level,
  coalesce(age, public.helpera_age_from_birth_date(about->>'birthDate')) as age,
  coalesce(availability_hours_week, nullif(interests->>'availabilityHoursWeek', '')::integer, 0) as availability_hours_week,
  coalesce(nullif(profile_completeness, 0), public.helpera_profile_completeness(about, skills, interests)) as profile_completeness,
  volunteer_reliability_score,
  volunteer_cancel_rate,
  active_tasks_count,
  created_at
from public.volunteer_profiles;

create or replace view public.ml_ngos as
select
  id::text as ngo_id,
  org_name as ngo_name,
  coalesce(ngo_city_raw, about->>'city', '') as ngo_city_raw,
  coalesce(ngo_city_clean, public.helpera_clean_text(about->>'city'), '') as ngo_city_clean,
  coalesce(org_type, about->>'orgType', '') as org_type,
  avg_response_time_hours,
  ngo_reliability_score,
  complaint_rate,
  active_tasks_count
from public.ngo_profiles;

create or replace view public.ml_tasks as
select
  id::text as task_id,
  ngo_profile_id::text as ngo_id,
  title,
  description,
  coalesce(requirements_raw, payload->>'requirements', payload->>'comment', '') as requirements_raw,
  coalesce(skills_raw, skills, payload->>'skills', '') as skills_raw,
  coalesce(skills_clean, skills, payload->>'skills', '') as skills_clean,
  coalesce(directions_raw, payload->>'directions', '') as directions_raw,
  coalesce(directions_clean, payload->>'directions', '') as directions_clean,
  coalesce(format_raw, format, payload->>'format', '') as format_raw,
  coalesce(format_clean, public.helpera_clean_text(format), public.helpera_clean_text(payload->>'format'), '') as format_clean,
  coalesce(city_raw, payload->>'city', '') as city_raw,
  coalesce(city_clean, public.helpera_clean_text(payload->>'city'), '') as city_clean,
  coalesce(deadline, date_end, nullif(payload->>'dateEnd', '')::date) as deadline,
  created_at,
  updated_at,
  coalesce(publication_status, status) as publication_status,
  task_quality_score,
  is_duplicate_candidate,
  capacity,
  current_applications
from public.tasks;

create or replace view public.ml_event_log as
select
  event_id,
  "timestamp",
  volunteer_id,
  task_id,
  ngo_id,
  event_type,
  status_from,
  status_to,
  dwell_ms,
  scroll_depth_pct,
  reason,
  payload_json
from public.ml_events;

create or replace view public.ml_ranking_dataset_base as
select
  v.volunteer_id,
  t.task_id,
  t.ngo_id,
  v.volunteer_id as qid,
  coalesce(a.status, 'shown') as interaction_status,
  case
    when bool_or(e.event_type in ('task_hidden', 'task_apply_cancelled', 'application_rejected')) then -1
    when bool_or(e.event_type in ('review_left_by_volunteer', 'review_left_by_ngo')) then 5
    when bool_or(e.event_type = 'application_accepted') then 4
    when bool_or(e.event_type = 'application_submitted') then 3
    when bool_or(e.event_type = 'task_details_viewed') then 2
    when bool_or(e.event_type = 'task_card_clicked') then 1
    else 0
  end as label_relevance,
  count(*) filter (where e.event_type = 'task_card_clicked') as clicked,
  count(*) filter (where e.event_type = 'task_details_viewed') as details_viewed,
  count(*) filter (where e.event_type = 'application_submitted') as applied,
  count(*) filter (where e.event_type = 'application_accepted') as accepted,
  count(*) filter (where e.event_type in ('review_left_by_volunteer', 'review_left_by_ngo')) as completed,
  count(*) filter (where e.event_type = 'task_hidden') as hidden,
  coalesce(max(e.dwell_ms), 0) as dwell_ms,
  coalesce(max(e.scroll_depth_pct), 0) as scroll_depth_pct,
  v.skills_clean as volunteer_skills_raw,
  t.skills_clean as task_skills_raw,
  v.directions_clean as volunteer_directions_raw,
  t.directions_clean as task_directions_raw,
  v.format_clean as volunteer_format_raw,
  t.format_clean as task_format_raw,
  v.city_clean as volunteer_city_raw,
  t.city_clean as task_city_raw,
  case when v.format_clean <> '' and v.format_clean = t.format_clean then 1 else 0 end as format_match,
  case when v.city_clean <> '' and v.city_clean = t.city_clean then 1 else 0 end as city_match,
  t.task_quality_score,
  char_length(t.description) as task_description_len,
  greatest(0, current_date - t.created_at::date) as task_age_days,
  greatest(0, t.deadline - current_date) as days_to_deadline,
  t.is_duplicate_candidate as task_is_duplicate_candidate,
  t.capacity,
  t.current_applications,
  case when t.capacity > 0 then round(t.current_applications::numeric / t.capacity, 4) else 0 end as application_pressure,
  v.volunteer_reliability_score,
  v.volunteer_cancel_rate,
  v.active_tasks_count as volunteer_active_tasks_count,
  v.profile_completeness as volunteer_profile_completeness,
  v.availability_hours_week as volunteer_availability_hours_week,
  n.ngo_reliability_score,
  n.avg_response_time_hours as ngo_avg_response_time_hours,
  n.complaint_rate as ngo_complaint_rate
from public.ml_events e
join public.ml_volunteers v on v.volunteer_id = e.volunteer_id
join public.ml_tasks t on t.task_id = e.task_id
left join public.ml_ngos n on n.ngo_id = t.ngo_id
left join public.applications a on a.id = e.application_id
group by v.volunteer_id, t.task_id, t.ngo_id, a.status, v.skills_clean, t.skills_clean,
  v.directions_clean, t.directions_clean, v.format_clean, t.format_clean, v.city_clean,
  t.city_clean, t.task_quality_score, t.description, t.created_at, t.deadline,
  t.is_duplicate_candidate, t.capacity, t.current_applications, v.volunteer_reliability_score,
  v.volunteer_cancel_rate, v.active_tasks_count, v.profile_completeness,
  v.availability_hours_week, n.ngo_reliability_score, n.avg_response_time_hours,
  n.complaint_rate;

alter table public.volunteer_profiles enable row level security;
alter table public.ngo_profiles enable row level security;
alter table public.tasks enable row level security;
alter table public.applications enable row level security;
alter table public.app_events enable row level security;
alter table public.ml_events enable row level security;
alter table public.ml_ranking_examples enable row level security;
alter table public.ml_label_rules enable row level security;
alter table public.ml_lgbm_groups enable row level security;
alter table public.ml_source_volunteers enable row level security;
alter table public.ml_source_ngos enable row level security;
alter table public.ml_source_tasks enable row level security;
alter table public.ml_source_events enable row level security;

drop policy if exists "Prototype read volunteer profiles" on public.volunteer_profiles;
create policy "Prototype read volunteer profiles" on public.volunteer_profiles for select using (true);
drop policy if exists "Prototype write volunteer profiles" on public.volunteer_profiles;
create policy "Prototype write volunteer profiles" on public.volunteer_profiles for all using (true) with check (true);

drop policy if exists "Prototype read ngo profiles" on public.ngo_profiles;
create policy "Prototype read ngo profiles" on public.ngo_profiles for select using (true);
drop policy if exists "Prototype write ngo profiles" on public.ngo_profiles;
create policy "Prototype write ngo profiles" on public.ngo_profiles for all using (true) with check (true);

drop policy if exists "Prototype read tasks" on public.tasks;
create policy "Prototype read tasks" on public.tasks for select using (true);
drop policy if exists "Prototype write tasks" on public.tasks;
create policy "Prototype write tasks" on public.tasks for all using (true) with check (true);

drop policy if exists "Prototype read applications" on public.applications;
create policy "Prototype read applications" on public.applications for select using (true);
drop policy if exists "Prototype write applications" on public.applications;
create policy "Prototype write applications" on public.applications for all using (true) with check (true);

drop policy if exists "Prototype read app events" on public.app_events;
create policy "Prototype read app events" on public.app_events for select using (true);
drop policy if exists "Prototype write app events" on public.app_events;
create policy "Prototype write app events" on public.app_events for all using (true) with check (true);

drop policy if exists "Prototype read ml events" on public.ml_events;
create policy "Prototype read ml events" on public.ml_events for select using (true);
drop policy if exists "Prototype write ml events" on public.ml_events;
create policy "Prototype write ml events" on public.ml_events for all using (true) with check (true);

drop policy if exists "Prototype read ml ranking examples" on public.ml_ranking_examples;
create policy "Prototype read ml ranking examples" on public.ml_ranking_examples for select using (true);
drop policy if exists "Prototype write ml ranking examples" on public.ml_ranking_examples;
create policy "Prototype write ml ranking examples" on public.ml_ranking_examples for all using (true) with check (true);

drop policy if exists "Prototype read ml label rules" on public.ml_label_rules;
create policy "Prototype read ml label rules" on public.ml_label_rules for select using (true);
drop policy if exists "Prototype write ml label rules" on public.ml_label_rules;
create policy "Prototype write ml label rules" on public.ml_label_rules for all using (true) with check (true);

drop policy if exists "Prototype read ml lgbm groups" on public.ml_lgbm_groups;
create policy "Prototype read ml lgbm groups" on public.ml_lgbm_groups for select using (true);
drop policy if exists "Prototype write ml lgbm groups" on public.ml_lgbm_groups;
create policy "Prototype write ml lgbm groups" on public.ml_lgbm_groups for all using (true) with check (true);

drop policy if exists "Prototype read ml source volunteers" on public.ml_source_volunteers;
create policy "Prototype read ml source volunteers" on public.ml_source_volunteers for select using (true);
drop policy if exists "Prototype write ml source volunteers" on public.ml_source_volunteers;
create policy "Prototype write ml source volunteers" on public.ml_source_volunteers for all using (true) with check (true);

drop policy if exists "Prototype read ml source ngos" on public.ml_source_ngos;
create policy "Prototype read ml source ngos" on public.ml_source_ngos for select using (true);
drop policy if exists "Prototype write ml source ngos" on public.ml_source_ngos;
create policy "Prototype write ml source ngos" on public.ml_source_ngos for all using (true) with check (true);

drop policy if exists "Prototype read ml source tasks" on public.ml_source_tasks;
create policy "Prototype read ml source tasks" on public.ml_source_tasks for select using (true);
drop policy if exists "Prototype write ml source tasks" on public.ml_source_tasks;
create policy "Prototype write ml source tasks" on public.ml_source_tasks for all using (true) with check (true);

drop policy if exists "Prototype read ml source events" on public.ml_source_events;
create policy "Prototype read ml source events" on public.ml_source_events for select using (true);
drop policy if exists "Prototype write ml source events" on public.ml_source_events;
create policy "Prototype write ml source events" on public.ml_source_events for all using (true) with check (true);

-- Recommendation events: impressions, clicks, and other feedback for the ML pipeline
create table if not exists public.recommendation_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null,
  volunteer_id text not null,
  task_id text,
  event_type text not null,
  rank integer,
  ml_score double precision,
  business_adjustment double precision,
  final_score double precision,
  match_percent integer,
  model_name text,
  schema_version text,
  created_at timestamptz not null default now()
);

create index if not exists recommendation_events_volunteer_id_idx on public.recommendation_events(volunteer_id);
create index if not exists recommendation_events_task_id_idx on public.recommendation_events(task_id);
create index if not exists recommendation_events_session_id_idx on public.recommendation_events(session_id);
create index if not exists recommendation_events_created_at_idx on public.recommendation_events(created_at);

alter table public.recommendation_events enable row level security;

drop policy if exists "Prototype read recommendation events" on public.recommendation_events;
create policy "Prototype read recommendation events" on public.recommendation_events for select using (true);
drop policy if exists "Prototype write recommendation events" on public.recommendation_events;
create policy "Prototype write recommendation events" on public.recommendation_events for all using (true) with check (true);
