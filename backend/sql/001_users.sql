-- ChronoMark · 001 — the users layer
--
-- Supabase Auth already keeps credentials, sessions and JWTs in auth.users.
-- This file adds everything the product needs on top of that: one profile per
-- user, the workspaces they own (a document or a video), the chat that belongs
-- to each workspace, and a usage ledger.
--
-- Run it once, in this order, against the project database. It is idempotent:
-- creating the objects again is a no-op, and every policy is dropped before it
-- is created.
--
--   psql "$DATABASE_URL" -f 001_users.sql

begin;

create extension if not exists pgcrypto;

-- ── migration bookkeeping ──────────────────────────────────────────────────
create table if not exists public.schema_migrations (
  name        text primary key,
  applied_at  timestamptz not null default now()
);

-- ── profiles ───────────────────────────────────────────────────────────────
-- 1:1 with auth.users. Identity lives in auth.users; everything a person can
-- change about themselves lives here.
create table if not exists public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text,
  display_name text,
  avatar_url   text,
  plan         text not null default 'free'
               check (plan in ('free', 'pro', 'team')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- ── workspaces ─────────────────────────────────────────────────────────────
-- One row per analysis the user owns. `kind` says which kind of workspace it
-- is, so a document and a video share the same ownership, list and chat shape.
create table if not exists public.workspaces (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users (id) on delete cascade,
  kind          text not null check (kind in ('document', 'video')),
  title         text,
  file_key      text,                                    -- R2 object key
  source_url    text,                                    -- YouTube import
  status        text not null default 'ready'
                check (status in ('queued', 'processing', 'ready', 'failed')),
  page_count    integer,
  duration_sec  numeric,
  meta          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists workspaces_user_created_idx
  on public.workspaces (user_id, created_at desc);

-- ── messages ───────────────────────────────────────────────────────────────
-- The conversation, in order. `citations` holds the page or timestamp anchors
-- the answer pointed at, so the UI can rebuild the answer exactly.
create table if not exists public.messages (
  id           bigint generated always as identity primary key,
  workspace_id uuid not null references public.workspaces (id) on delete cascade,
  user_id      uuid not null references auth.users (id) on delete cascade,
  role         text not null check (role in ('user', 'assistant', 'system')),
  content      text not null,
  citations    jsonb not null default '[]'::jsonb,
  created_at   timestamptz not null default now()
);

create index if not exists messages_workspace_created_idx
  on public.messages (workspace_id, created_at);

-- ── usage ledger ───────────────────────────────────────────────────────────
-- One row per billable unit (an ask, an upload, a transcription). Kept
-- separate from the workspace so a plan limit can be counted without reading
-- the content.
create table if not exists public.usage_events (
  id           bigint generated always as identity primary key,
  user_id      uuid not null references auth.users (id) on delete cascade,
  workspace_id uuid references public.workspaces (id) on delete set null,
  kind         text not null check (kind in ('ask', 'upload', 'transcribe', 'document_ai')),
  tokens       integer,
  seconds      numeric,
  created_at   timestamptz not null default now()
);

create index if not exists usage_events_user_created_idx
  on public.usage_events (user_id, created_at desc);

-- ── updated_at ─────────────────────────────────────────────────────────────
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at
  before update on public.profiles
  for each row execute function public.touch_updated_at();

drop trigger if exists workspaces_touch_updated_at on public.workspaces;
create trigger workspaces_touch_updated_at
  before update on public.workspaces
  for each row execute function public.touch_updated_at();

-- ── a profile for every new user ───────────────────────────────────────────
-- Sign-up happens in auth.users; the profile row has to appear with it, or the
-- first request from a brand-new account has nothing to read.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, display_name)
  values (
    new.id,
    new.email,
    coalesce(
      nullif(new.raw_user_meta_data ->> 'full_name', ''),
      nullif(new.raw_user_meta_data ->> 'name', ''),
      split_part(coalesce(new.email, ''), '@', 1)
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ── row level security ─────────────────────────────────────────────────────
-- The publishable key is public, so the database itself has to be the wall:
-- every row is readable and writable only by the account that owns it.
alter table public.profiles     enable row level security;
alter table public.workspaces   enable row level security;
alter table public.messages     enable row level security;
alter table public.usage_events enable row level security;

drop policy if exists "profiles: read own"   on public.profiles;
create policy "profiles: read own"   on public.profiles
  for select using (auth.uid() = id);

drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "workspaces: own rows" on public.workspaces;
create policy "workspaces: own rows" on public.workspaces
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "messages: own rows" on public.messages;
create policy "messages: own rows" on public.messages
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "usage: read own" on public.usage_events;
create policy "usage: read own" on public.usage_events
  for select using (auth.uid() = user_id);

insert into public.schema_migrations (name)
values ('001_users')
on conflict (name) do nothing;

commit;
