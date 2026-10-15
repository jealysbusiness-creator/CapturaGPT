create table if not exists public.accounts (
    id uuid primary key default gen_random_uuid(),
    username text unique not null,
    password_hash text not null,
    hardware_id text,
    credits_remaining integer not null default 50 check (credits_remaining >= 0),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    last_login_at timestamptz
);
alter table public.accounts enable row level security;
revoke all on public.accounts from anon, authenticated;

create or replace function public.consume_account_credit(p_username text, p_hardware_id text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare r public.accounts;
begin
 select * into r from public.accounts where username=p_username for update;
 if not found or not r.is_active then return jsonb_build_object('ok',false,'error','INVALID_CREDENTIALS'); end if;
 if r.hardware_id is null or r.hardware_id='' then
   update public.accounts set hardware_id=p_hardware_id where id=r.id;
 elsif r.hardware_id <> p_hardware_id then
   return jsonb_build_object('ok',false,'error','DEVICE_MISMATCH');
 end if;
 if r.credits_remaining <= 0 then return jsonb_build_object('ok',false,'error','INSUFFICIENT_CREDITS'); end if;
 update public.accounts set credits_remaining=credits_remaining-1 where id=r.id returning * into r;
 return jsonb_build_object('ok',true,'credits_left',r.credits_remaining);
end $$;
revoke all on function public.consume_account_credit(text,text) from public, anon, authenticated;
grant execute on function public.consume_account_credit(text,text) to service_role;
