-- 자료 만족도 평가 표. Supabase → SQL Editor → 붙여넣고 Run. 여러 번 실행해도 안전하다.
-- 한 사용자가 한 강의(세션)에 평가 1개 (다시 저장하면 수정). 점수는 1~5점, 칸 이름 = r_ + 문항 key (app/feedback.py).

create table if not exists public.feedback (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  lecture_id uuid not null references public.lectures(id) on delete cascade,
  stage text not null,                 -- A1, B1 …
  course_type text not null,           -- A~E
  r_overall smallint not null check (r_overall between 1 and 5),
  r_completeness smallint not null check (r_completeness between 1 and 5),
  r_accuracy smallint not null check (r_accuracy between 1 and 5),
  r_structure smallint not null check (r_structure between 1 and 5),
  r_traceability smallint not null check (r_traceability between 1 and 5),
  r_writing_space smallint not null check (r_writing_space between 1 and 5),
  r_time_saving smallint not null check (r_time_saving between 1 and 5),
  r_stage_specific smallint check (r_stage_specific between 1 and 5),  -- A1: 원문 정확도, B1: 수식·예제
  reuse text check (reuse in ('yes', 'maybe', 'no')),
  usage text[] not null default '{}',  -- preview, in_class, review, exam, not_yet
  time_saved text,                     -- none, lt30, 30_60, 60_120, gt120
  issues text[] not null default '{}', -- missing, wrong, added, order, math, too_long, hard_to_read, none
  issue_pages text not null default '',
  best text not null default '',
  worst text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, lecture_id)
);
create index if not exists feedback_course_idx on public.feedback (course_id);
alter table public.feedback enable row level security;

-- 분석용 요약 (Table Editor에서 보기). security_invoker 라서 RLS가 그대로 적용된다 (공개 키로는 못 읽음).
create or replace view public.feedback_by_stage with (security_invoker = true) as
select stage, course_type, count(*) as responses,
       round(avg(r_overall), 2) as overall,
       round(avg(r_completeness), 2) as completeness,
       round(avg(r_accuracy), 2) as accuracy,
       round(avg(r_structure), 2) as structure,
       round(avg(r_traceability), 2) as traceability,
       round(avg(r_writing_space), 2) as writing_space,
       round(avg(r_time_saving), 2) as time_saving,
       round(avg(r_stage_specific), 2) as stage_specific,
       round(100.0 * avg((reuse = 'yes')::int), 1) as reuse_yes_pct
from public.feedback
group by stage, course_type;
