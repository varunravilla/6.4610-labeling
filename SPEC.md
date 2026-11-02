# Spec: Truth Social industry-impact labeling app

Status: ready-for-agent
Supersedes `LABELING_AGENT_BRIEF.md` wherever the two differ. Anything this spec does not mention (lexicon terms, hard-drop rules) is taken from the brief unchanged.

## Problem Statement

Our 6.4610 project (Wyatt Alford, Matthew Zhou, Varun Ravilla, Kevin Zhang) trains a classifier that predicts how a Trump Truth Social post affects specific industries, and tests whether those predictions help forecast industry ETF out-performance. That needs human labels: for each post, whether it is trade-related or market-relevant at all, and for each industry, whether the post implies a positive, negative, neutral, or uncertain effect.

The raw archive has about 37,700 posts, most of them irrelevant (rallies, endorsements, legal fights). The four of us have roughly 10 hours each. We need to (1) filter the archive down to posts plausibly about trade or markets, ordered so the most useful posts get labeled first, and (2) give all four of us one shareable link where we label those posts quickly, with every label saved in one central place that survives anyone's laptop being closed.

## Solution

A two-part system.

**Offline pipeline (Python, run once by Varun).** Builds a frozen candidate queue from `data.json` and `djt_posts_dec2025.csv`: hard drops, a keyword lexicon to decide who is a candidate, then a Gemini (free tier) yes/no relevance screen that only sets queue order. Loads the ordered queue into a Supabase Postgres database.

**Labeling site (static page on GitHub Pages, data in Supabase).** A teammate opens the link, picks their name, enters the team passcode, and is shown one post at a time from a shared pull queue. They answer "Relevant?" and, if yes, set an impact for each of ten core industries (with a "rest → neutral" shortcut), optionally add extra industries, and submit. A random 20% of posts are served to a second person for agreement measurement. A Resolve view lets a third person settle disagreements into final gold labels. An export script pulls everything back into CSVs in the project folder.

Queue order:

1. Second-term posts (2025-01-20 onward) Gemini marked relevant
2. Earlier posts (2022-02-14 to 2025-01-19) Gemini marked relevant
3. All posts Gemini marked not relevant

Within each group: keyword tier ascending, then number of matched terms descending, then `created_at` ascending.

## User Stories

### Building the queue

1. As Varun, I want one command that reads both source files and produces the candidate queue, so that the queue is reproducible.
2. As Varun, I want reposts, deleted posts, empty/media-only posts, link-only posts, and duplicate texts dropped before matching, so that nobody labels junk.
3. As Varun, I want Twitter rows in the CSV ignored, so that only Truth Social posts enter the queue.
4. As Varun, I want posts after 2026-10-31 excluded, so that the window is fixed before labeling.
5. As Varun, I want the lexicon stored as a plain tiered text file, so that the team can read and amend it.
6. As Varun, I want matching to respect token boundaries, so that `port` does not match `portion` and `ev` does not match `every`.
7. As Varun, I want each candidate to record its keyword tier and matched terms, so that the report can describe how posts entered the queue.
8. As Varun, I want posts that name a trading partner together with a sum or rate to enter at tier 3 even with no lexicon hit, so that obvious trade posts are not missed.
9. As Varun, I want the non-matching posts written to an excluded file with a 100-post year-stratified sample, so that someone can spot-check recall.
10. As Varun, I want a manifest with the window, candidate ids, and a hash of candidate texts, so that we can prove the queue did not change after labeling began.

### Gemini relevance screen

11. As Varun, I want Gemini to give every candidate a yes/no for "trade-related or could plausibly affect markets or industries", so that relevant posts are labeled first.
12. As Varun, I want the screen to use the free tier by batching about 25 posts per request, so that it costs nothing and fits the daily quota.
13. As Varun, I want the screen to read `GEMINI_API_KEY` from the environment and exit with a clear message if it is missing, so that no key is ever committed.
14. As Varun, I want screen results cached to disk and the script resumable, so that a rate-limit or quota stop can be resumed the next day without re-paying calls.
15. As Varun, I want the model id, prompt hash, and run time recorded, so that the report can describe the screen exactly.
16. As Varun, I want a post Gemini says "no" to stay in the queue at the back rather than be deleted, so that a screen error never removes a post from labeling.
17. As Varun, I want a missing or unparseable Gemini answer treated as "yes", so that failures err toward human review.

### Loading and setup

18. As Varun, I want one command that creates or verifies the Supabase schema and loads the ordered queue, so that setup is repeatable.
19. As Varun, I want the loader to refuse to reload posts once any label exists, so that labels are never orphaned by a rebuild.
20. As Varun, I want the 20% double-label set chosen at load time with a fixed seed, stratified by queue group and tier, so that overlap is random and reproducible.
21. As Varun, I want to set the team passcode with a command, stored hashed, so that it can be rotated without code changes.
22. As Varun, I want the service-role key used only by local scripts and never shipped in the page, so that the public site cannot bypass the database rules.

### Logging in

23. As a teammate, I want to open one link with no account to create, so that I can start labeling immediately.
24. As a teammate, I want to pick my name from Wyatt, Matthew, Varun, Kevin and enter the team passcode, so that my labels are attributed to me.
25. As a teammate, I want the page to remember my name and passcode in this browser, so that I do not retype them each session.
26. As a teammate, I want a clear error on a wrong passcode, so that I know why saving failed.
27. As the team, we want every write rejected when the passcode is wrong, so that a stranger who finds the URL cannot add labels.

### Labeling a post

28. As a teammate, I want to see one post at a time with its text, date and time, and a link to the original, so that I can judge it in context.
29. As a teammate, I want a short guideline shown beside the post, so that I apply the rubric consistently.
30. As a teammate, I want to answer "Relevant?" yes or no first, so that irrelevant posts take one click.
31. As a teammate, I want a "no" to save immediately and load the next post, so that the common case is fast.
32. As a teammate, I want a "yes" to reveal the ten core industry rows, so that I only see them when they matter.
33. As a teammate, I want each core row to offer positive, negative, neutral, and uncertain, so that I label exactly the four classes the classifier predicts.
34. As a teammate, I want every core row to start blank, so that I make a deliberate choice rather than accept a default.
35. As a teammate, I want a "rest → neutral" button, so that I can set only the affected industries and fill the rest in one click.
36. As a teammate, I want submit disabled until every core row has a value, so that no label is incomplete.
37. As a teammate, I want an optional "+ industry" control to add defense, aerospace, minerals, shipping, housing, or other (with a short name), each with an impact, so that effects outside the core list are captured.
38. As a teammate, I want keyboard shortcuts (Y/N for relevance, number keys for impacts, Enter to submit, S to skip), so that I can label without the mouse.
39. As a teammate, I want to skip a post I am unsure about, so that I am not blocked; it should come back to me only after my other available work.
40. As a teammate, I want a Back button that reopens my previous submission for editing, so that I can fix a mistake.
41. As a teammate, I want re-submitting a post to replace my earlier label for it, so that each person has at most one label per post.
42. As a teammate, I want the page to work on a phone, so that I can label anywhere.

### Shared pull queue

43. As a teammate, I want to be served the next post in queue order that still needs a label from me, so that the most useful posts are done first.
44. As the team, we want a post that is not in the double-label set to be done after one label, so that hours are not wasted.
45. As the team, we want a double-label post to be served to a second, different person after the first label, so that we can measure agreement.
46. As the team, we want a post claimed for a few minutes when it is served, so that two people labeling at the same moment do not get the same post.
47. As the team, we want an abandoned claim to expire, so that a closed tab does not lock a post forever.
48. As a teammate, I want labeling to continue into earlier-era posts automatically once second-term relevant posts are done, so that I can keep going without anyone reassigning work.
49. As a teammate, I want a progress line showing remaining and completed counts per queue group, so that I can see how far along we are.
50. As the team, we want a per-person count of labels, so that we can see the split of work.

### Resolving disagreements

51. As a teammate, I want a Resolve view listing double-labeled posts where the two labels disagree, so that disagreements get settled.
52. As a resolver, I want only posts I labeled neither copy of to be offered to me, so that resolution is independent.
53. As a resolver, I want to see both labels side by side, so that I can see exactly where they differ.
54. As a resolver, I want to choose one label or edit a final answer and save it, so that the post gets a gold label.
55. As a resolver, I want an optional one-line note, so that tricky calls are documented without slowing me down.
56. As the team, we want a disagreement defined as any difference in relevance, any core impact, or the set of extra industries and their impacts, so that the rule is unambiguous.

### Getting the data out

57. As Varun, I want one command that exports all labels to CSV in the project folder, so that training code reads local files.
58. As Varun, I want a wide file with one row per annotator per post, so that I can inspect labels quickly.
59. As Varun, I want a long file with one row per (post, annotator, industry), so that it feeds the post–industry classifier directly.
60. As Varun, I want a gold file with one row per (post, industry) built from single labels plus resolved overlap labels, so that there is one training target per pair.
61. As Varun, I want each exported row to carry tier, queue group, era, Gemini answer, `created_at`, and whether it was double-labeled or resolved, so that analysis can slice by them.
62. As Varun, I want an agreement report with Cohen's kappa on relevance and on per-industry impact for double-labeled posts, computed before resolution, so that the report can state annotator agreement.
63. As Varun, I want a collect report listing any stored label that fails validation, so that bad rows are caught before training.

## Implementation Decisions

### Modules

- **Candidate builder.** Pure function from the two source files plus the lexicon to an ordered candidate list, the excluded list, the excluded sample, and the manifest. Rules from the brief: hard drops, lexicon matching, tiering, and partner-plus-money. Window changes to start 2022-02-14, end 2026-10-31, with an `era` field: `second_term` if `created_at >= 2025-01-20T00:00:00Z`, else `earlier`.
- **Gemini screener.** Takes candidates and returns `{post_id: relevant | not_relevant}` plus run metadata.
  - Batches about 25 posts per request and asks for structured JSON keyed by post id, at temperature 0.
  - The model is the best Gemini Flash-class model available on the free tier at build time; verify the current model name and rate limits then.
  - Caches per-post answers on disk, backs off on rate-limit errors, and resumes from the cache.
  - The prompt contains only the post text, its timestamp, and the relevance definition, never other posts or market data.
- **Queue orderer.** Pure function: candidates plus screen results to rows with `queue_group` (1, 2, 3 as in the Solution), `queue_rank`, and `double_label` (seeded 20% sample, seed 4610, stratified by `queue_group` × `tier`).
- **Supabase loader.** Applies the schema, inserts posts, and sets the passcode hash. It refuses to touch the `posts` table if any label exists.
- **Database API.** Postgres `SECURITY DEFINER` functions called through Supabase RPC. The page never reads or writes tables directly; RLS denies all direct access to the anon role.
- **Labeling page.** A single static HTML/JS page served by GitHub Pages. It uses supabase-js with the project URL and anon key and talks only to the RPC functions. Name and passcode are kept in `localStorage`.
- **Exporter and agreement report.** A local Python script using the service-role key. It writes the CSVs and the reports.

### Industries

- **Core, required when relevant:** `steel_aluminum`, `autos`, `semiconductors`, `agriculture`, `energy`, `pharmaceuticals`, `technology`, `financials`, `consumer_retail`, `broad_economy`. Reference ETFs for annotator context: SLX, CARZ, SOXX, MOO, XLE, PPH, XLK, XLF, XRT. `broad_economy` has no ETF.
- **Extra, optional:** `defense`, `aerospace`, `minerals_metals`, `shipping`, `lumber_housing`, `other`. `other` requires a short free-text name.
- **Impact values:** `positive`, `negative`, `neutral`, `uncertain`.
- **Not-relevant posts:** a label with `relevant = false` is stored with every core industry `neutral` and no extras.

### Rubric shown beside the post

- **Relevant:** yes when the post concerns cross-border trade policy or flows (tariffs, duties, quotas, trade deals, import or export restrictions, trade deficits) or states a policy or concrete claim that would change costs, prices, production, employment, or demand for an industry or the economy over the next year. Rallies, endorsements, legal fights, media criticism, and cheerleading that names no policy or mechanism are not relevant.
- **Impact:** judge the following year, conditional on the stated policy being implemented, using only the post and what was public at its timestamp.
  - `neutral`: no identifiable material effect.
  - `uncertain`: the text is too thin, or effects compete.
  - `broad_economy`: across-the-board claims. Named or implied industries still get their own value when the mechanism differs.

### Schema (Postgres)

- `posts`: `id` (text pk), `created_at`, `text`, `url`, `era`, `tier`, `matched_terms` (text[]), `gemini_relevant` (bool), `queue_group`, `queue_rank` (unique int), `double_label` (bool).
- `labels`: `post_id`, `annotator` (one of the four names), `relevant` (bool), `impacts` (jsonb map core industry → impact), `extras` (jsonb array of `{industry, other_name?, impact}`), `labeled_at`, `updated_at`. Primary key `(post_id, annotator)`.
- `skips`: `post_id`, `annotator`, `skipped_at`.
- `claims`: `post_id`, `annotator`, `expires_at`. Claims last 10 minutes.
- `gold`: `post_id` (pk), `resolver`, `relevant`, `impacts`, `extras`, `note`, `resolved_at`.
- `settings`: passcode hash (bcrypt via pgcrypto).
- **Validation:** the database checks the impact maps. All ten core keys must be present with valid values, and extras must be well formed.

### RPC contract

Every call takes `annotator` and `passcode` and fails with a clear error code if either is invalid.

- `next_post()`: returns the post that needs this person, or null when there is none.
  - A post needs this person when the person has not labeled it, it has fewer labels than its target (1, or 2 if `double_label`), and no other person holds a live claim on it.
  - Posts the person has not skipped come first, by `queue_rank`. Then skipped posts, by `queue_rank`.
  - Returning a post claims it for the caller.
- `submit_label(post_id, relevant, impacts, extras)`: upserts the caller's label and releases the claim. Rejects:
  - a post that would exceed its label target, unless the caller already has a label on it (an edit)
  - an invalid impact map
- `skip(post_id)`: records the skip and releases the claim.
- `my_previous(before_labeled_at)`: returns the caller's most recent label before a point in time, for Back.
- `progress()`: counts per `queue_group` (remaining and done) and per annotator.
- `next_conflict()`: returns a double-labeled post with two labels that disagree, no gold row, and where the caller labeled neither copy. Returns both labels.
- `submit_gold(post_id, relevant, impacts, extras, note)`: same independence check, then upserts gold.

### Hosting

- **Repo:** new public GitHub repo `varunravilla/6.4610-labeling`. Pages serves the static site directory.
- **Gitignored:** raw source files, generated CSVs, the Gemini cache, and any `.env` file. The Supabase URL and anon key are committed in the page config, and are public by design.
- **Setup Varun does by hand:** create the free Supabase project, give the URL, anon key, and service-role key to the local scripts via `.env`, and choose the passcode.

### Exports

Written to `labeling/` locally:
- **`labels_wide.csv`:** one row per (post, annotator), with impacts flattened to one column per core industry plus an `extras` cell.
- **`labels_long.csv`:** one row per (post, annotator, industry).
- **`gold.csv`:** one row per (post, industry).
  - Single-label posts use their one label.
  - Double-labeled posts use agreement or the gold row.
  - Unresolved conflicts are omitted and listed in the collect report.
- **`agreement.txt`:** kappa on relevance, kappa on core impacts over (post, industry) pairs, computed on double-labeled posts before gold.
- **`collect_report.txt`:** unresolved conflicts and rows that fail validation.

All rows carry `era`, `queue_group`, `tier`, `gemini_relevant`, `created_at`, `double_label`, and `resolved`.

### Dropped from the brief

The pilot, rationale fields, the `implicit` flag, `country_targets`, `scope_reason`, `no_other_material_effects`, split relevance booleans, fixed round-robin assignment, FastAPI/SQLite/tunnel hosting, and full LLM labeling.

## Testing Decisions

Good tests here exercise behavior through the highest seam and assert on outputs a teammate or the training code would see, not on internal helpers or SQL text.

### Seam 1: queue builder (Python, pytest)

`build_queue(json_records, csv_rows, lexicon, screen_results) -> ordered rows`, run with small fixture inputs and no network. Covers:
- **Hard drops:** RT, deleted, link-only, duplicate.
- **Matching:** token boundaries (`port` vs `portion`, `ev` vs `every`) and stem rules.
- **Queue entry and ordering:** partner-plus-money entry, era split at 2025-01-20, group, tier, and rank ordering.
- **Double-label sample:** the seeded sample is about 20% per stratum and stable across runs.
- **Screen failures:** a missing Gemini answer is treated as relevant.

The Gemini screener is tested only for batching, cache resume, and parse-failure handling, with a fake client.

### Seam 2: database RPC API (pytest against a local Supabase or plain Postgres with the migration applied)

Calls the RPC functions as the four annotators. Covers:
- A wrong passcode is rejected.
- `next_post` respects queue order, label targets, and the "not already labeled by me" rule.
- Concurrent `next_post` calls return different posts because of claims, and an expired claim frees its post.
- Skipped posts return last.
- A third label on a double-label post is rejected, and an edit by an existing labeler is accepted.
- An invalid impact map is rejected.
- `next_conflict` never offers a post to either of its labelers.
- `progress` counts match the inserted labels.

### Not unit-tested

The HTML page, which gets one manual pass: label, skip, back, and resolve on desktop and phone. The exporter is checked by running it on a database seeded by the Seam 2 tests and asserting the CSV schemas and the gold rule.

### Prior art

None. The project folder has no existing code or tests.

## Out of Scope

- Full LLM labeling of the form, and comparison of LLM labels to gold. This is deferred, and the schema leaves room for it.
- Training the FinBERT classifier and fetching ETF prices.
- Real per-person authentication (OAuth).
- Editing the lexicon or rebuilding the queue after labeling has started.
- An admin UI for editing or deleting other people's labels. That goes through the export plus SQL if ever needed.
- The claude.ai test page published during planning (https://claude.ai/artifact/NFC49zAdAUMgvVig63LJcr) is unused and should be deleted.

## Further Notes

- **Capacity:** about 1,000–1,500 labeled posts for 4 people × about 10 hours. Queue group 1 should fit well inside that, and group 2 absorbs the remaining hours.
- **Look-ahead:** the Gemini screener's knowledge cutoff postdates the posts. It only sets queue order, never a label, so look-ahead bias cannot reach the training targets. Note this in `RUN.md`.
- **Free tier data use:** Gemini free-tier inputs may be used by Google. The inputs are public posts, so this is acceptable.
- **Proposal changes:** the classifier is pairwise over the ten core industries. This expands the proposal's three (steel, autos, semiconductors). The forecasting half can still restrict to industries with a chosen ETF.
