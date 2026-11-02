-- Labeling database. Safe to re-run: it only creates what is missing and replaces functions.
-- The public site uses the anon key and may only call the functions granted to anon below;
-- every table has RLS on with no policies, so direct table access is denied.

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;

create table if not exists annotators (name text primary key);

create table if not exists settings (key text primary key, value text not null);

create table if not exists posts (
  id text primary key,
  created_at timestamptz not null,
  text text not null,
  url text not null default '',
  era text not null check (era in ('second_term', 'earlier')),
  tier int not null,
  matched_terms text[] not null default '{}',
  gemini_relevant boolean,
  queue_group int not null,
  queue_rank int not null unique,
  double_label boolean not null default false
);

create table if not exists labels (
  post_id text not null references posts(id),
  annotator text not null references annotators(name),
  relevant boolean not null,
  impacts jsonb not null,
  extras jsonb not null default '[]',
  labeled_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (post_id, annotator)
);
create index if not exists labels_annotator_time on labels (annotator, labeled_at);

create table if not exists skips (
  post_id text not null references posts(id),
  annotator text not null references annotators(name),
  skipped_at timestamptz not null default now(),
  primary key (post_id, annotator)
);

create table if not exists claims (
  post_id text primary key references posts(id),
  annotator text not null references annotators(name),
  expires_at timestamptz not null
);

create table if not exists gold (
  post_id text primary key references posts(id),
  resolver text not null references annotators(name),
  relevant boolean not null,
  impacts jsonb not null,
  extras jsonb not null default '[]',
  note text not null default '',
  resolved_at timestamptz not null default now()
);

alter table annotators enable row level security;
alter table settings enable row level security;
alter table posts enable row level security;
alter table labels enable row level security;
alter table skips enable row level security;
alter table claims enable row level security;
alter table gold enable row level security;
revoke all on annotators, settings, posts, labels, skips, claims, gold from public, anon, authenticated;

-- ---------------------------------------------------------------- helpers

create or replace function _core_industries() returns text[] language sql immutable as $$
  select array['steel_aluminum','autos','semiconductors','agriculture','energy','pharmaceuticals',
               'technology','financials','consumer_retail','broad_economy']
$$;

create or replace function _check_login(p_annotator text, p_passcode text) returns void
language plpgsql security definer set search_path = public, extensions as $$
declare h text;
begin
  if not exists (select 1 from annotators where name = p_annotator) then
    raise exception 'unknown_annotator';
  end if;
  select value into h from settings where key = 'passcode_hash';
  if h is null or crypt(coalesce(p_passcode, ''), h) <> h then
    raise exception 'bad_passcode';
  end if;
end $$;

-- Raises invalid_label unless the label is complete and well formed.
create or replace function _check_label(p_relevant boolean, p_impacts jsonb, p_extras jsonb) returns void
language plpgsql immutable set search_path = public as $$
declare k text; e jsonb;
begin
  if p_relevant is null or jsonb_typeof(p_impacts) <> 'object' or jsonb_typeof(p_extras) <> 'array' then
    raise exception 'invalid_label: missing fields';
  end if;
  if (select array_agg(x order by x) from jsonb_object_keys(p_impacts) x)
     is distinct from (select array_agg(x order by x) from unnest(_core_industries()) x) then
    raise exception 'invalid_label: impacts must cover exactly the core industries';
  end if;
  for k in select jsonb_object_keys(p_impacts) loop
    if p_impacts->>k not in ('positive','negative','neutral','uncertain') then
      raise exception 'invalid_label: bad impact for %', k;
    end if;
    if not p_relevant and p_impacts->>k <> 'neutral' then
      raise exception 'invalid_label: a not-relevant post has every industry neutral';
    end if;
  end loop;
  if not p_relevant and jsonb_array_length(p_extras) > 0 then
    raise exception 'invalid_label: a not-relevant post has no extra industries';
  end if;
  for e in select * from jsonb_array_elements(p_extras) loop
    if e->>'industry' not in ('defense','aerospace','minerals_metals','shipping','lumber_housing','other')
       or e->>'impact' not in ('positive','negative','neutral','uncertain')
       or (e->>'industry' = 'other' and coalesce(trim(e->>'other_name'), '') = '') then
      raise exception 'invalid_label: bad extra industry %', e;
    end if;
  end loop;
end $$;

-- Extras compared as a set, so order in the array never creates a false disagreement.
create or replace function _norm_extras(p jsonb) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(e order by e->>'industry', e->>'other_name', e->>'impact'), '[]')
  from jsonb_array_elements(p) e
$$;

create or replace function _post_json(p posts) returns jsonb language sql stable as $$
  select jsonb_build_object('id', p.id, 'created_at', p.created_at, 'text', p.text, 'url', p.url,
    'era', p.era, 'tier', p.tier, 'queue_group', p.queue_group, 'queue_rank', p.queue_rank,
    'double_label', p.double_label)
$$;

-- ---------------------------------------------------------------- labeling API

create or replace function next_post(p_annotator text, p_passcode text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare p posts;
begin
  perform _check_login(p_annotator, p_passcode);

  -- A post this person already holds (e.g. after a page reload) comes back first.
  select posts.* into p from claims join posts on posts.id = claims.post_id
  where claims.annotator = p_annotator and claims.expires_at > now()
    and not exists (select 1 from labels l where l.post_id = posts.id and l.annotator = p_annotator)
  limit 1;

  if p.id is null then
    select posts.* into p from posts
    where not exists (select 1 from labels l where l.post_id = posts.id and l.annotator = p_annotator)
      and (select count(*) from labels l where l.post_id = posts.id) < (case when posts.double_label then 2 else 1 end)
      and not exists (select 1 from claims c where c.post_id = posts.id and c.expires_at > now()
                      and c.annotator <> p_annotator)
    order by exists (select 1 from skips s where s.post_id = posts.id and s.annotator = p_annotator),
             posts.queue_rank
    limit 1
    for update of posts skip locked;
  end if;

  if p.id is null then
    return null;
  end if;
  insert into claims (post_id, annotator, expires_at) values (p.id, p_annotator, now() + interval '10 minutes')
  on conflict (post_id) do update set annotator = excluded.annotator, expires_at = excluded.expires_at;
  return _post_json(p);
end $$;

create or replace function submit_label(p_annotator text, p_passcode text, p_post_id text,
                                        p_relevant boolean, p_impacts jsonb, p_extras jsonb) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare p posts; editing boolean;
begin
  perform _check_login(p_annotator, p_passcode);
  perform _check_label(p_relevant, p_impacts, p_extras);
  select * into p from posts where id = p_post_id for update;
  if p.id is null then
    raise exception 'unknown_post';
  end if;
  editing := exists (select 1 from labels where post_id = p_post_id and annotator = p_annotator);
  if not editing and (select count(*) from labels where post_id = p_post_id)
                     >= (case when p.double_label then 2 else 1 end) then
    raise exception 'post_full';
  end if;
  insert into labels (post_id, annotator, relevant, impacts, extras)
  values (p_post_id, p_annotator, p_relevant, p_impacts, _norm_extras(p_extras))
  on conflict (post_id, annotator) do update
    set relevant = excluded.relevant, impacts = excluded.impacts, extras = excluded.extras, updated_at = now();
  delete from claims where post_id = p_post_id and annotator = p_annotator;
  delete from skips where post_id = p_post_id and annotator = p_annotator;
  return jsonb_build_object('ok', true, 'edited', editing);
end $$;

create or replace function skip_post(p_annotator text, p_passcode text, p_post_id text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
begin
  perform _check_login(p_annotator, p_passcode);
  insert into skips (post_id, annotator) values (p_post_id, p_annotator)
  on conflict (post_id, annotator) do update set skipped_at = now();
  delete from claims where post_id = p_post_id and annotator = p_annotator;
  return jsonb_build_object('ok', true);
end $$;

-- The caller's label submitted just before p_before (null = their latest), with its post, for Back.
create or replace function previous_label(p_annotator text, p_passcode text, p_before timestamptz) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare r jsonb;
begin
  perform _check_login(p_annotator, p_passcode);
  select jsonb_build_object('post', _post_json(p), 'relevant', l.relevant, 'impacts', l.impacts,
                            'extras', l.extras, 'labeled_at', l.labeled_at)
  into r
  from labels l join posts p on p.id = l.post_id
  where l.annotator = p_annotator and (p_before is null or l.labeled_at < p_before)
  order by l.labeled_at desc
  limit 1;
  return r;
end $$;

create or replace function progress(p_annotator text, p_passcode text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare r jsonb;
begin
  perform _check_login(p_annotator, p_passcode);
  with counts as (
    select p.queue_group, p.double_label, (select count(*) from labels l where l.post_id = p.id) n
    from posts p
  )
  select jsonb_build_object(
    'groups', (select jsonb_agg(jsonb_build_object(
                 'queue_group', queue_group,
                 'total', total, 'done', done) order by queue_group)
               from (select queue_group, count(*) total,
                            count(*) filter (where n >= case when double_label then 2 else 1 end) done
                     from counts group by queue_group) g),
    'annotators', (select jsonb_object_agg(a.name, (select count(*) from labels l where l.annotator = a.name))
                   from annotators a),
    'mine', (select count(*) from labels l where l.annotator = p_annotator),
    'conflicts_open', (select count(*) from posts p
                       where p.double_label and not exists (select 1 from gold g where g.post_id = p.id)
                         and (select count(distinct (l.relevant, l.impacts, l.extras)) from labels l
                              where l.post_id = p.id) = 2)
  ) into r;
  return r;
end $$;

-- ---------------------------------------------------------------- resolving disagreements

create or replace function next_conflict(p_annotator text, p_passcode text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
declare p posts;
begin
  perform _check_login(p_annotator, p_passcode);
  select posts.* into p from posts
  where posts.double_label
    and not exists (select 1 from gold g where g.post_id = posts.id)
    and not exists (select 1 from labels l where l.post_id = posts.id and l.annotator = p_annotator)
    and (select count(distinct (l.relevant, l.impacts, l.extras)) from labels l where l.post_id = posts.id) = 2
  order by posts.queue_rank
  limit 1;
  if p.id is null then
    return null;
  end if;
  return jsonb_build_object('post', _post_json(p), 'labels',
    (select jsonb_agg(jsonb_build_object('annotator', l.annotator, 'relevant', l.relevant,
                                         'impacts', l.impacts, 'extras', l.extras) order by l.annotator)
     from labels l where l.post_id = p.id));
end $$;

create or replace function submit_gold(p_annotator text, p_passcode text, p_post_id text, p_relevant boolean,
                                       p_impacts jsonb, p_extras jsonb, p_note text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
begin
  perform _check_login(p_annotator, p_passcode);
  perform _check_label(p_relevant, p_impacts, p_extras);
  if exists (select 1 from labels where post_id = p_post_id and annotator = p_annotator) then
    raise exception 'not_independent: you labeled this post';
  end if;
  if not exists (select 1 from posts where id = p_post_id and double_label)
     or (select count(*) from labels where post_id = p_post_id) < 2 then
    raise exception 'not_a_conflict';
  end if;
  insert into gold (post_id, resolver, relevant, impacts, extras, note)
  values (p_post_id, p_annotator, p_relevant, p_impacts, _norm_extras(p_extras), coalesce(p_note, ''))
  on conflict (post_id) do update set resolver = excluded.resolver, relevant = excluded.relevant,
    impacts = excluded.impacts, extras = excluded.extras, note = excluded.note, resolved_at = now();
  return jsonb_build_object('ok', true);
end $$;

create or replace function check_login(p_annotator text, p_passcode text) returns jsonb
language plpgsql security definer set search_path = public, extensions as $$
begin
  perform _check_login(p_annotator, p_passcode);
  return jsonb_build_object('ok', true);
end $$;

create or replace function annotator_names() returns jsonb
language sql security definer set search_path = public as $$
  select coalesce(jsonb_agg(name order by name), '[]') from annotators
$$;

-- ---------------------------------------------------------------- grants

grant usage on schema public to anon, authenticated;
revoke all on all functions in schema public from public, anon, authenticated;
grant execute on function next_post(text, text), submit_label(text, text, text, boolean, jsonb, jsonb),
  skip_post(text, text, text), previous_label(text, text, timestamptz), progress(text, text),
  next_conflict(text, text), submit_gold(text, text, text, boolean, jsonb, jsonb, text),
  check_login(text, text), annotator_names() to anon, authenticated;
