-- 사용자 프로필 (이름·학교·학과·학년·나이·사진). Supabase → SQL Editor → 붙여넣고 Run. 여러 번 실행해도 안전하다.
-- 사진 파일은 Storage lectures 버킷의 {user_id}/avatar.jpg (비공개, 서버를 거쳐서만 보임). avatar_at = 사진 바꾼 시각.

alter table public.profiles
  add column if not exists display_name text,
  add column if not exists school text,
  add column if not exists department text,
  add column if not exists grade text,        -- 1~6, grad(대학원), etc(기타)
  add column if not exists age smallint,
  add column if not exists avatar_at timestamptz,
  add column if not exists updated_at timestamptz;

alter table public.profiles drop constraint if exists profiles_age_check;
alter table public.profiles add constraint profiles_age_check check (age is null or age between 10 and 99);
alter table public.profiles drop constraint if exists profiles_grade_check;
alter table public.profiles add constraint profiles_grade_check
  check (grade is null or grade in ('1', '2', '3', '4', '5', '6', 'grad', 'etc'));
