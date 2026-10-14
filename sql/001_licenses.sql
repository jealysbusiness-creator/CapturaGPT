-- Ejecutar una sola vez en Supabase SQL Editor. Solo el backend usa service_role.
create table if not exists public.licenses (
    license_key text primary key,
    hardware_id text,
    credits_remaining integer not null default 50 check (credits_remaining >= 0),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    constraint license_key_not_blank check (length(btrim(license_key)) > 0)
);

alter table public.licenses enable row level security;
revoke all on table public.licenses from public, anon, authenticated;
grant select, insert, update, delete on table public.licenses to service_role;

create or replace function public.consume_credit(
    p_license_key text,
    p_hardware_id text
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_license public.licenses%rowtype;
    v_remaining integer;
begin
    if nullif(btrim(p_hardware_id), '') is null then
        return jsonb_build_object('ok', false, 'error', 'INVALID_HARDWARE_ID');
    end if;

    -- El bloqueo de fila serializa el primer enlace y todos los descuentos.
    select * into v_license
      from public.licenses
     where license_key = p_license_key
     for update;

    if not found or v_license.is_active is not true then
        return jsonb_build_object('ok', false, 'error', 'INVALID_LICENSE');
    end if;
    if nullif(btrim(v_license.hardware_id), '') is not null
       and v_license.hardware_id <> p_hardware_id then
        return jsonb_build_object('ok', false, 'error', 'DEVICE_MISMATCH');
    end if;
    if v_license.credits_remaining <= 0 then
        return jsonb_build_object('ok', false, 'error', 'INSUFFICIENT_CREDITS');
    end if;

    update public.licenses
       set hardware_id = p_hardware_id,
           credits_remaining = credits_remaining - 1
     where license_key = p_license_key
     returning credits_remaining into v_remaining;

    return jsonb_build_object('ok', true, 'credits_left', v_remaining);
end;
$$;

revoke all on function public.consume_credit(text, text) from public, anon, authenticated;
grant execute on function public.consume_credit(text, text) to service_role;
