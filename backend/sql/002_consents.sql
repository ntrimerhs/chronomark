-- ChronoMark · 002 — consent ledger
--
-- Text from a user's files and their questions is sent to DeepSeek, which keeps
-- it on servers in China. There is no EU adequacy decision for that transfer, so
-- the only lawful basis is the user's explicit consent (GDPR Art. 49(1)(a)), and
-- we have to be able to prove it. Every grant and every withdrawal is a new row;
-- nothing is updated or deleted. The newest row per (user, kind) is the current
-- state, and a consent given to an older policy version no longer counts.
--
--   psql "$DATABASE_URL" -f 002_consents.sql

begin;

create table if not exists public.user_consents (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users (id) on delete cascade,
  kind        text not null check (kind in ('china_transfer', 'marketing')),
  granted     boolean not null,
  version     text not null,
  created_at  timestamptz not null default now()
);

create index if not exists user_consents_user_kind_idx
  on public.user_consents (user_id, kind, created_at desc);

alter table public.user_consents enable row level security;

-- A user may read their own history. Writes go through the API with the service
-- key (which bypasses RLS), so the browser cannot forge a consent.
drop policy if exists user_consents_select_own on public.user_consents;
create policy user_consents_select_own on public.user_consents
  for select using (auth.uid() = user_id);

insert into public.schema_migrations (name) values ('002_consents')
  on conflict (name) do nothing;

commit;
