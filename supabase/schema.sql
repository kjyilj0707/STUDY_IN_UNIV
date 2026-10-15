-- STUDY_IN_UNIV 데이터베이스 구조. Supabase 대시보드 → SQL Editor → 붙여넣고 Run.
-- 여러 번 실행해도 안전하다 (if not exists).
-- 모든 표에 RLS를 켜고 정책은 두지 않는다 → 브라우저(공개 키)로는 못 읽고, 서버(secret key)만 읽고 쓴다.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.courses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  course_name text not null,
  professor text not null default '',
  semester text not null default '',
  primary_type text not null check (primary_type in ('A', 'B', 'C', 'D', 'E')),
  secondary_types text[] not null default '{}',
  evaluation text not null default '',
  reasons jsonb not null default '[]',
  weeks jsonb not null default '[]',
  syllabus_text text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists courses_user_idx on public.courses (user_id, created_at);

create table if not exists public.lectures (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  week text not null default '',
  stage text not null,
  pages int,
  status text not null default 'ready',   -- ready / running / done / error
  estimate jsonb,
  note text,
  omissions jsonb,
  cost_usd numeric,
  truncated boolean not null default false,
  error text,
  pdf_path text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists lectures_course_idx on public.lectures (course_id, created_at);
create index if not exists lectures_user_idx on public.lectures (user_id);

-- 사용 기록: signup, login, classify, course_create, lecture_upload, generate_start, generate_done, generate_error, note_view, note_download, note_print
create table if not exists public.events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  type text not null,
  course_id uuid,
  lecture_id uuid,
  data jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists events_user_type_idx on public.events (user_id, type, created_at);

alter table public.profiles enable row level security;
alter table public.courses enable row level security;
alter table public.lectures enable row level security;
alter table public.events enable row level security;

-- 강의 PDF 저장소 (비공개)
insert into storage.buckets (id, name, public)
values ('lectures', 'lectures', false)
on conflict (id) do nothing;

-- 자료 만족도 평가 표는 supabase/002_feedback.sql (처음부터 만들 때는 이 파일 다음에 실행)
