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

drop trigger if exists set_volunteer_profiles_updated_at on public.volunteer_profiles;
create trigger set_volunteer_profiles_updated_at
before update on public.volunteer_profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_ngo_profiles_updated_at on public.ngo_profiles;
create trigger set_ngo_profiles_updated_at
before update on public.ngo_profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_tasks_updated_at on public.tasks;
create trigger set_tasks_updated_at
before update on public.tasks
for each row execute function public.set_updated_at();

drop trigger if exists set_applications_updated_at on public.applications;
create trigger set_applications_updated_at
before update on public.applications
for each row execute function public.set_updated_at();

alter table public.volunteer_profiles enable row level security;
alter table public.ngo_profiles enable row level security;
alter table public.tasks enable row level security;
alter table public.applications enable row level security;
alter table public.app_events enable row level security;

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
