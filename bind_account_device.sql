create or replace function public.bind_account_device(
    p_username text,
    p_hardware_id text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    account_row public.accounts;
begin
    select * into account_row
    from public.accounts
    where username = p_username
    for update;

    if not found or not account_row.is_active then
        return jsonb_build_object('ok', false, 'error', 'INVALID_CREDENTIALS');
    end if;

    if account_row.hardware_id is not null
       and account_row.hardware_id <> ''
       and account_row.hardware_id <> p_hardware_id then
        return jsonb_build_object('ok', false, 'error', 'DEVICE_MISMATCH');
    end if;

    update public.accounts
    set hardware_id = p_hardware_id,
        last_login_at = now()
    where id = account_row.id
    returning * into account_row;

    return jsonb_build_object(
        'ok', true,
        'credits_left', account_row.credits_remaining
    );
end;
$$;

revoke all on function public.bind_account_device(text, text)
    from public, anon, authenticated;
grant execute on function public.bind_account_device(text, text)
    to service_role;
