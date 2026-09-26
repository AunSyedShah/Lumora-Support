# AI Tool Usage Declaration

As required by SRS §1.8.19 and §1.10.18, this file records every AI tool used during development.

---

## Entry 1 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Project scaffolding: authentication and the configurable complaint catalog |
| **Assistance requested** | Summarise the SRS; propose a fictional organisation; build the custom user model, JWT auth and catalog CRUD APIs with Django Ninja; write the seed data and tests |
| **Files affected** | `support_nova_project/settings.py`, `support_nova_project/api.py`, `support_nova_project/urls.py`, `accounts/*` (models, auth, schemas, api, admin, tests), `catalog/*` (models, schemas, api, admin, tests, `management/commands/seed_catalog.py`), `config/catalog.json`, `.gitignore`, `.env.example` |
| **Changes made** | Custom `User` with roles (customer/agent/reviewer/manager/admin) and a customer type; JWT access/refresh tokens using PyJWT and Ninja `HttpBearer`; role checks; Department / Category / Subcategory / SLARule models with CRUD endpoints addressed by code; `/catalog/taxonomy` endpoint; idempotent seed command for the Lumora Home Technologies catalog (11 departments, 12 categories, 37 subcategories, 4 SLA rules) |
| **Tests performed** | `python manage.py test`: 23 tests covering registration, login, refresh, expired/invalid tokens, role permissions, catalog CRUD, adding a category live, duplicate codes and protected deletes. All passing. |
| **Verifying team members** | _TODO: names of the team members who reviewed and understood this code_ |

## Entry 2 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Knowledge base: document upload, validation, parsing, chunking, versioning, retrieval (SRS Steps 4–7, 25) |
| **Assistance requested** | Build the `knowledge_base` app using Django Ninja, plus sample Lumora policy documents |
| **Files affected** | `knowledge_base/*` (models, parsing, chunking, validation, services, retrieval, schemas, api, admin, tests, `management/commands/generate_sample_docs.py`), `sample_documents/source/*.md`, `sample_documents/*.pdf/.docx`, `settings.py` (media + upload limit), `support_nova_project/api.py`, `accounts/auth.py` (`STAFF_ROLES`), `.gitignore` |
| **Changes made** | `PolicyDocument`/`PolicyChunk` models; checks for file type, size, emptiness, file signature, duplicate hash, duplicate doc_id+version and dates; PDF (PyMuPDF), DOCX (python-docx) and TXT/MD parsing; metadata read from the document header, with form fields taking priority; chunking by numbered section headings (section, heading and page kept); automatic Active→Previous→Superseded versioning; precedence rule (policy > SOP > FAQ); keyword search over usable chunks only |
| **Tests performed** | 18 new tests (41 in total, all passing): real PDF/DOCX parsing, version transitions, rejected uploads, blank form fields, permissions, search ignoring outdated and future-dated versions, chunking edge cases. A bug was found during manual inspection: PDF ligatures (`ﬀ`) broke the "Effective Date" match. Fixed with Unicode NFKC normalisation. |
| **Verifying team members** | _TODO_ |

## Entry 3 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Complaint Resolution Rule Matrix and the deterministic rule engine (SRS Step 8, deliverable 5), plus the full knowledge base |
| **Assistance requested** | Plan and build Step 3: rule models, CSV import/export, an evaluation engine that does not use GenAI, the policy-reference check, rule data and the remaining policy documents |
| **Files affected** | `rules/*` (models, conditions, engine, importer, references, schemas, api, admin, tests, `management/commands/load_rules.py`), `config/rules/resolution_rules.csv`, `config/rules/escalation_rules.csv`, `config/catalog.json` (subcategory keywords), `catalog/models.py` (`keywords`, severity ranks), `catalog/schemas.py`, `catalog/api.py`, `seed_catalog.py`, `knowledge_base/parsing.py` (title fix), `knowledge_base/management/commands/load_sample_documents.py`, `sample_documents/source/*.md` (18 new, 2 updated) |
| **Changes made** | Keyword classifier for subcategories; `ResolutionRule` (113 rules) and `EscalationRule` (35 rules) with a validated condition language; engine that picks the most specific rule, applies every matching escalation rule, detects primary and secondary issues and supporting departments, reports missing facts and explains each decision; all-or-nothing CSV import with row-level errors; `/rules/evaluate`, `/rules/policy-check`, `/rules/stats`; 22 policy documents, including deliberate conflicts (the CMP-SOP and FAQ still say 14 days and a 10 USD voucher) |
| **Tests performed** | 32 new tests (73 in total, all passing): SRS trap scenarios (calm safety complaint, angry low-risk complaint, escalation trap, multi-issue, legal threat, repeat, VIP, refund window, missing information, prompt injection), adding a category live and changing an escalation threshold live, import rollback, export/import round trip, detection of broken policy references. Manual check: all 148 rule references resolve against the loaded knowledge base. A bug was found: a document without a title line lost its first section heading. Fixed, with a regression test. |
| **Verifying team members** | _TODO_ |

## Entry 4 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Complaint intake (SRS Steps 9–11, 50–54) with vector search: FAISS and fastembed |
| **Assistance requested** | Decide whether a vector database fits the SRS; add FAISS and embeddings; build complaint submission, validation, pre-processing, and duplicate and repeat detection |
| **Files affected** | `vector_search/*` (embeddings, FAISS index wrapper), `complaints/*` (models, preprocessing, security, facts, duplicates, services, schemas, api, admin, tests, `management/commands/seed_demo_data.py`), `catalog/*` (`Product` model, schema, endpoints, seed), `config/catalog.json` (products, extra keywords), `settings.py` (embedding and threshold settings), `support_nova_project/api.py`, `.gitignore`, `.env.example` |
| **Changes made** | Local `bge-small-en-v1.5` embeddings (fastembed/ONNX) stored in the database, with an exact FAISS `IndexFlatIP` search that can be restricted to one customer's complaints; `Order` and `Complaint` models; submission with sanitisation (HTML, invisible characters, NFKC), card-number masking (Luhn check), metadata extraction, prompt-injection flags, reference validation that doesn't reveal other customers' orders, rule facts calculated from order data (business days late), rejection of exact duplicates, near-duplicate and repeat detection that follows chains of earlier complaints; attachment validation; staff views, similar complaints, rule-engine preview; deterministic demo data (5 staff accounts, 60 customers, 156 orders) |
| **Tests performed** | 28 new tests (101 in total, all passing), including one test using the real embedding model. Thresholds were calibrated on 16 realistic complaint pairs: similarity alone overlapped (0.73–0.89 vs 0.59–0.78), so similarity was combined with a keyword-classifier check (15/16 correct). Bugs found during manual end-to-end runs: a reworded complaint scored just below the threshold (fixed by recalibrating), the third complaint in a chain counted only one earlier complaint (fixed by following earlier links), and `related_complaint` was always null in the submit response (fixed; covered by a test). |
| **Verifying team members** | _TODO_ |

## Entry 5 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Pipeline 1, the GenAI complaint-intelligence pipeline (SRS Steps 12–50), plus semantic policy retrieval |
| **Assistance requested** | Plan and build Step 5: versioned prompts, context building, the DeepSeek client, output schema, validation, controlled retries and evidence logging |
| **Files affected** | `genai_pipeline/*` (models, output_schema, prompts, context, client, validation, pipeline, schemas, api, admin, tests, `load_prompts` and `export_genai_schema` commands), `prompt_templates/complaint_analysis/v1.0.txt`, `v1.1.txt`, `schemas/complaint_analysis.schema.json`, `knowledge_base/retrieval.py` (semantic and hybrid RRF search), `knowledge_base/models.py` + `services.py` (chunk embeddings), `embed_policy_chunks` command, `knowledge_base/api.py` (search modes), `settings.py`, `.env.example` |
| **Changes made** | Pipeline 1 is independent of the rule engine (it does its own retrieval and never sees rule results); complaint text is wrapped as untrusted data with delimiter stripping; the live taxonomy is inserted into the prompt; Pydantic output schema plus checks against the live catalog; retries that send the model its own error messages; unknown policy references kept as validation issues rather than retried away; every attempt, request, raw response, token count, prompt version and policy version is logged; prompt versions are immutable and can be activated or rolled back |
| **Tests performed** | 22 new tests (123 in total, all passing), with the DeepSeek call mocked. Live tests against DeepSeek: prompt v1.0 failed on escalated cases (the example only showed `escalation_notes: null`), which led to prompt v1.1 and retry hints listing the expected keys. Next, `deepseek-flash` was found to spend output tokens on hidden reasoning by default (empty or cut-off JSON, and temperature ignored). Measured on 3 complaints: thinking disabled took 1 attempt and 3.6–7.7 s; low effort needed retries and took 9.6–22.3 s. Result: `GENAI_THINKING=disabled`. With that setting, the calm safety complaint came out Critical/P0 and the injection attempt got `manipulation_detected: true`, no compensation and P3. Bug fixed: calling `/analyze` without a body returned 400 (tone is now a query parameter). |
| **Verifying team members** | _TODO_ |

## Entry 6 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic), using the built-in browser to read the DeepSeek API docs |
| **Purpose** | Tune Pipeline 1 for DeepSeek's context caching, rate limits, error codes and thinking mode |
| **Assistance requested** | Read the DeepSeek docs (thinking mode, KV cache, rate limits, error codes, pricing, chat completions API) and apply what matters |
| **Files affected** | `prompt_templates/complaint_analysis/v1.2.txt`, `genai_pipeline/client.py`, `pipeline.py`, `models.py` (+ migration), `schemas.py`, `tests.py`, `settings.py` |
| **Changes made** | Prompt v1.2 reorders the content so every part that is the same for all complaints comes first (the cache only reuses identical prefixes); cache-hit tokens are logged per attempt and per analysis; a fixed app-level `user_id` is sent (the cache is isolated per user_id, and customer data must not go into it); clear handling of 402 insufficient balance; a `content_filter` finish reason stops retrying and goes to manual review |
| **Tests performed** | All 123 tests pass. Live DeepSeek measurement on 3 complaints over 2 rounds: 65–67% of prompt tokens were served from cache for *different* complaints and 93–94% on re-analysis, every run took under 7 s, and the classifications were identical across both rounds. |
| **Verifying team members** | _TODO_ |

## Entry 7 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Pipeline 2 (Python ground-truth validation), the comparison engine, the verification decision and the final resolution (SRS Steps 23, 26, 28–31, 34–35, 39, 46, 57; FR xlv–li; NFR 4) |
| **Assistance requested** | Plan and build Step 6: independent validation of the GenAI output with no GenAI involved, scoring, Verified / Manual Review decision, a single process endpoint, and the comparison report |
| **Files affected** | `python_validation/*` (models, checks, text_checks, decision, services, schemas, api, admin, tests), `complaints/facts.py` (`rule_facts`), `complaints/api.py`, `complaints/tests.py`, `rules/engine.py` + `schemas.py` (`rule_decided`), `config/catalog.json` (keywords), `settings.py` |
| **Changes made** | Two rule-engine views (independent classification, and rules evaluated for GenAI's own subcategory); checks for category, subcategory, routing, urgency, priority, escalation (a missed escalation is enforced), compensation, follow-up, clarification, policy applicability (applicable / conditional / not applicable / outdated, including a semantic-relatedness test), precedence measured against the designated governing document, policy version drift, hallucinated references and amounts, unsupported promises (refund, compensation, exception, deadline, timelines not found in any policy), required and prohibited actions (embeddings plus keyword overlap), and internal consistency; score = 100 − 25/10/3 per finding; manual-review reasons; final resolution with enforcement (rule priority, escalation floor, routing, added actions, compensation removed, response marked for rewrite); comparison report as JSON or CSV |
| **Tests performed** | 18 new tests (141 in total, all passing). Calibration on real DeepSeek outputs: required-action threshold 0.70 (covered 0.72–0.98, missing 0.63). Five false positives were found on real outputs and fixed: "unable to" not treated as negation; "I will check your eligibility for a refund" read as a promise; policy applicability based on category alone; precedence judged against "a policy" when the governing document is an SOP; over-prioritisation not counted as a report mismatch. Design change after live testing: the final priority now follows the rule matrix, so an angry customer's tone cannot raise it (the SRS sentiment trap). End-to-end processing takes 4.7–7.8 s (NFR: 20 s). |
| **Verifying team members** | _TODO_ |

## Entry 8 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Workflow: manual review queue, reviewer actions, audit trail, status lifecycle, assignment, SLA, follow-ups, customer replies (SRS Steps 41, 55–61, 66; FR lix–lxvi) |
| **Assistance requested** | Plan and build Step 7 |
| **Files affected** | `workflow/*` (models, audit, lifecycle, services, schemas, api, admin, tests), `complaints/models.py` (working-state, SLA and follow-up fields), `complaints/schemas.py` (customer dashboard fields, staff fields), `complaints/api.py` (Step 66 filters), `complaints/services.py` (submission audit), `accounts/models.py` (`User.department`), `seed_demo_data` (one agent per department), `python_validation/services.py` + `api.py` (routing moved into the workflow), `python_validation/decision.py` (critical routing), `rules/engine.py` + `schemas.py` (escalation target department) |
| **Changes made** | Complaint working state separate from the untouched original GenAI and validation results; append-only audit log with before/after snapshots; explicit status-transition table; automatic assignment to the least-loaded agent in the department; SLA due dates from the priority, with the time spent awaiting the customer excluded (SLA-POL 2.1) and on-track / at-risk / breached / met / missed states; follow-up scheduling; review queue ordered by priority and SLA; approve, reject, modify, reclassify (rules re-evaluated), reassign, escalate and regenerate; agent notes, status changes, send response (blocked during review or when the response has unsupported promises and hasn't been edited), follow-up done; customer reply (resumes the SLA) and reopen within 7 days; customer dashboard fields (resolution status, department, latest update) |
| **Tests performed** | 21 new tests (162 in total, all passing). Bugs found by the tests: a verified escalated complaint was moved on to "assigned" and lost its escalated status; when the GenAI missed a safety escalation, the enforced escalation still left the complaint owned by Logistics (the target department of the escalation rule now takes ownership, as NFR 4 requires). Design change: escalated complaints get an owner immediately even while a review is pending (SAF-POL 2.2: Product Safety within 1 hour). Checked on the live dev data by re-routing the 6 real processed complaints. |
| **Verifying team members** | _TODO_ |

## Entry 9 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Code review and bug fixing of Step 7 (workflow) |
| **Assistance requested** | Find and fix the bugs in Step 7 |
| **Files affected** | `workflow/services.py`, `workflow/lifecycle.py`, `workflow/api.py`, `workflow/schemas.py`, `workflow/tests.py`, `python_validation/services.py` (`check_outgoing_response`, `policy_texts_for`), `python_validation/api.py`, `complaints/models.py` (+ migration `sla_clock_start`), `settings.py` (`DEFAULT_SLA_PRIORITY`) |
| **Changes made** | A line-by-line review found 11 bugs; each was first reproduced with a failing regression test, then fixed. **B1** GenAI failure left a safety complaint without escalation, owner, department or SLA: the rule-engine result is now used as a fallback. **B2** no SLA without a priority: a default SLA priority is used. **B3** approving an escalated complaint gave it no owner. **B4** de-escalation left the status as "escalated" and the resolution out of date: new `_sync_escalation` and `_update_resolution` helpers. **B5** reclassifying into a new subcategory without rules crashed (null priority): the current or default priority is kept. **B6** a complaint was set to "assigned" when no agent was available. **B7** the generic status endpoint could set "escalated" or "assigned" without the related data, and close complaints under review. **B8** the unsafe-response block could be bypassed by editing one character, and responses written by people were never checked: every outgoing text is now checked (promises, prohibited actions, invented facts), with a reviewer-only audited override. **B9** complaints closed without being resolved showed "breached" forever. **B10** reopened complaints were breached immediately: the SLA clock restarts on reopen. **B11** processing a resolved or closed complaint overwrote final decisions: now refused with 409. The test structure was also fixed (subclassed tests re-ran inherited tests and deleted a shared media folder). |
| **Tests performed** | 11 new regression tests (all failed before the fixes: 10 failures and 1 crash), 173 in total, all passing. The B8 check was run against the 6 real DeepSeek responses in the dev database: no false positives. |
| **Verifying team members** | _TODO_ |

## Entry 10 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Role-based access: agents limited to complaints assigned to them (SRS FR ii, Step 62, deliverable 10 "unauthorized-access tests") |
| **Assistance requested** | Check what the SRS says about agent access; then restrict agents to their own assignments |
| **Files affected** | `complaints/permissions.py` (new), `complaints/api.py`, `genai_pipeline/api.py`, `python_validation/api.py`, `workflow/api.py`, tests in `complaints`, `genai_pipeline`, `python_validation`, `workflow` |
| **Changes made** | One shared `visible_complaints()` / `get_visible_complaint()` used by every staff endpoint: reviewers, managers and admins see all complaints; agents see only complaints assigned to them; anything outside a user's scope returns 404 so complaint IDs can't be discovered by probing. This covers complaint list and detail, history, similar complaints (results filtered), rule preview, attachments, orders (agents only see customers they handle), GenAI analyses and evidence, validation results, processing, workflow item, audit trail, notes, agent actions, SLA and follow-up lists. The comparison report (all complaints) is now reviewer-only. |
| **Tests performed** | 5 new unauthorized-access tests (another agent's complaint returns 404 on 10 read endpoints and 4 actions; the list contains only own assignments; access follows reassignment; SLA list scoped; reports and review queue forbidden; processing or analysing unassigned complaints refused). Existing tests that used an agent to read unassigned complaints were updated to use a reviewer. 178 tests in total, all passing. |
| **Verifying team members** | _TODO_ |

## Entry 11 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Process complaints automatically on submission, so agents (who only see their own assignments) receive new complaints without a manual processing step |
| **Assistance requested** | Fix the consequence of agent scoping: only reviewers, managers and admins could process new, unassigned complaints |
| **Files affected** | `workflow/services.py` (`auto_process`), `workflow/management/commands/process_pending.py` (new), `complaints/api.py` (submit), `settings.py` (`AUTO_PROCESS_ON_SUBMIT`), `workflow/tests.py` |
| **Changes made** | Submission now runs GenAI analysis, validation and routing straight away (synchronously, within the 20 s NFR; no background threads, to avoid SQLite locking). Processing never breaks a submission: a GenAI failure falls back to the rule engine; any unexpected error places the complaint in the manual review queue with an SLA and the error in the audit log. `process_pending` retries unprocessed complaints (after an outage or a bulk import). Switched off in the test suite so tests never call the real API. |
| **Tests performed** | 5 new tests (183 in total, all passing): submit, then auto-assigned, then the agent can open it; a GenAI outage still escalates a safety complaint to Product Safety; an unexpected failure (no active prompt) lands in the review queue; switching the feature off works; `process_pending` catches up. Live test through the HTTP API with DeepSeek: submit and process took 7.4 s. That complaint went to manual review, correctly: the GenAI grounded its answer only in the FAQ because policy retrieval did not give it the Warranty Policy. Investigation: FAISS works (173/173 indexed); the doorbell complaint ("offline, does nothing") is semantically closer to connectivity text, WAR-POL 2.1 was at semantic rank 7 and was pushed out of the top 8 by keyword noise. An experiment adding the document title to chunk embeddings did not improve results (1 better, 2 worse, 3 unchanged over 6 queries), so it was not adopted. Retrieval tuning is deferred until it can be measured on the labelled complaint dataset. |
| **Verifying team members** | _TODO_ |

## Entry 12 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Dashboards, analytics, trend detection, reports and export (SRS Steps 62–68, deliverable 9) |
| **Assistance requested** | Plan and build Step 8 |
| **Files affected** | `reports/*` (data, analytics, dashboards, catalog, export, api, tests), `python_validation/comparison.py` (moved `comparison_row` out of `api.py`), `workflow/lifecycle.py` (SLA rule cache), `settings.py`, `support_nova_project/api.py`, `pyproject.toml` (pandas, openpyxl) |
| **Changes made** | One role-scoped pandas DataFrame feeds every dashboard, analytic and report, so all numbers agree. Agent dashboard (own open assignments with recommendation, validation, suggested response, escalation warning, SLA); admin dashboard (distributions, escalations, resolution status, SLA risks, GenAI/Python mismatches, manual reviews by reason, trend alerts); analytics (volume per day, 10 breakdowns, escalation rate, resolution time mean/median/p90 by priority, repeats, SLA outcomes, verification); trend detection with explicit thresholds (rising, recurring product issues, repeated service failures, escalation spikes as mean + 2 std); 9 reports; CSV (UTF-8 BOM), Excel (Report and Summary sheets), PDF (PyMuPDF, landscape A4). |
| **Tests performed** | 13 new tests (196 in total, all passing): exact analytics numbers, filters, dashboards and their scoping (organisation-wide endpoints return 403 for agents and customers), rising, recurring, repeated and spike detection, every report in every format (the xlsx opens in openpyxl, the PDF opens in PyMuPDF). Visual check of a rendered PDF found the 19-column comparison table running off the page; wide reports now declare their key PDF columns and the PDF lists the hidden ones (with a test). Performance with 10,000 complaints (in a rolled-back transaction): frame 1.3 s, analytics + trends 0.09 s, report + CSV 1.8 s, Excel 3.7 s. |
| **Verifying team members** | _TODO_ |

## Entry 13 — 2026-09-25

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) to write the generator code; DeepSeek (`deepseek-flash`, JSON mode, thinking disabled) to write the complaint text |
| **Purpose** | The SRS complaint dataset: 500 unique complaints with expected routing, urgency and escalation (SRS "Complaint Dataset", "Hint" minimums) |
| **Assistance requested** | Create a synthetic dataset with "approach C": Python decides what each complaint is about and its expected labels; an LLM only writes the words |
| **Files affected** | `complaint_dataset/*` (new app: scenarios, specs, expected, generator, orders, loader, evaluation, csv_io, summary, 4 commands, tests), `rules/engine.py` (evaluate accepts a list of known subcategories), `rules/tests.py`, `sample_complaints/*` (specs, generated text, complaints.csv, README) |
| **Changes made** | 500 specs built with a fixed seed. Core complaints are built per resolution rule: random order facts are drawn and a draw is kept only if the matrix selects that rule. Plus escalation triggers, calm-critical, multi-issue, ambiguous, incomplete, boundary / outdated-policy, contradictory, policy-exception, unsupported-refund, 24 prompt-injection (12 payloads inserted word for word by code), 12 near-duplicates, 19 repeats, and 20 customers with an unrelated second complaint. Expected labels = the rule matrix applied to the true scenario, never to the text. The text generator has its own prompt, client and user_id, never sees the labels, and checks every output (length, placeholders, invented numbers, extra escalation triggers that would change the labels, identical near-duplicates), retrying once with a hint. The loader creates orders dated so the system calculates exactly the spec's facts, and submits through the normal intake. 100 complaints (20% of every group, linked ones together) are held out as the test split. |
| **Tests performed** | 18 new tests (spec determinism, SRS minimums, target rules hit, order facts exact on every weekday, CSV round trip, text checks, retry-then-flag with a mocked LLM, loader placeholders / links / facts). Generation: 500/500, 11 retried once, 0 flagged, about 318k tokens. Human review of a pilot (12 complaints, twice) led to three fixes: exact day counts became natural phrasing, contradictory cases no longer receive the true dates, and harmless inherent triggers (e.g. "shock" in an electric-shock complaint) are no longer treated as errors. The first load found an identical "near-duplicate" (the intake correctly rejected it as an exact duplicate; that case was regenerated) and a 10-minute load caused by hashing the password for each of ~460 customers (now hashed once: 43 s). |
| **Verifying team members** | _TODO_ |

## Entry 14 — 2026-09-26

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic) |
| **Purpose** | Measure the system on the dataset and tune it, using the dev split for tuning and the held-out test split only for the final measurement |
| **Assistance requested** | Finish the test-split evaluation, then tune keywords, duplicate thresholds, injection patterns and retrieval |
| **Files affected** | `config/catalog.json` (keywords), `rules/conditions.py` ("a ~ b" near keywords), `complaints/security.py`, `settings.py` (NEAR_DUPLICATE 0.93 → 0.97, REPEAT_CERTAIN 0.80 → 0.85, GENAI_STANDING_POLICIES), `genai_pipeline/context.py`, `prompt_templates/complaint_analysis/v1.3.txt`, `complaint_dataset/evaluation.py` (review metrics), `evaluate_dataset` (`--sample`), tests in `rules`, `complaints`, `genai_pipeline` |
| **Changes made** | Keyword review of the misclassified dev complaints: "a ~ b" keywords (both words within 10 words, e.g. "refund ~ refused"); 18 subcategories extended; generic phrases removed ("want a refund" made damaged-item complaints look like refund disputes; "never arrived" made missed appointments look like lost parcels; "fire" matched "could cause a fire"). Injection patterns: new generic patterns (closing the complaint tags, notes to the AI, fake role tags, JSON label fields, "classify this complaint as") and customer demands such as "refund me immediately" are no longer flagged. Duplicate thresholds re-tuned on 41 dev pairs. Prompt v1.3 always includes the escalation procedure, SLA policy and routing rules (cached prefix); on 100 dev complaints it raised final escalation accuracy from 88% to 95% and fully correct complaints from 77% to 84%, at 6.9 s and 81% cache hits. Evaluation now separates reviews that caught a GenAI error from unnecessary ones. |
| **Tests performed** | Test split (100 unseen complaints), before → after: final all-fields correct 72% → 81%, escalation 84% → 93%, priority 93% → 96%; Pipeline 2 alone subcategory 60% → 77% (dev 63% → 87%: part of the dev gain did not carry over); injections flagged at intake 1/5 → 5/5 (GenAI detected 5/5 both times; the test payloads are the same 12 types as dev, so this intake number is optimistic); repeat/near-duplicate type 4/7 → 7/7, no wrong links. Manual review: 58% of complaints (before: 68% of those not needing it); 74.5% of GenAI errors are caught, 3 GenAI errors reached the final result unreviewed, 12 reviews were unnecessary. Known weak spots: repeats and multi-issue complaints (UNRESOLVED_PREVIOUS overlaps with the repeated issue; HARDWARE_MALFUNCTION vs REPLACEMENT_REQUEST), GenAI priority (60%, it defaults to P2; the final result uses the rule matrix). 217 tests, all passing. |
| **Verifying team members** | _TODO_ |

## Entry 15 — 2026-09-26

| Field | Details |
|---|---|
| **Tool name** | Claude Code (Anthropic); DeepSeek to regenerate 16 dataset complaints |
| **Purpose** | Fix the weak spots found by the evaluation: overlapping subcategories (follow-up complaints classified as "unresolved previous complaint"; malfunction vs replacement request vs firmware failure) |
| **Assistance requested** | Fix the weak spots properly, develop on the dev split only, and state how often the test split was measured |
| **Files affected** | `catalog/models.py` + migration 0004 (`is_fallback`, `takes_precedence_over`), `catalog/schemas.py`, `catalog/api.py`, `seed_catalog`, `config/catalog.json` (definitions, keywords), `rules/engine.py` (`_demoted`), `genai_pipeline/context.py` (taxonomy shows definitions), `complaint_dataset/scenarios.py`, tests in `catalog`, `rules`, `genai_pipeline`, `sample_complaints/*` |
| **Changes made** | The overlap is handled by configuration, not code. A subcategory can be a fallback (UNRESOLVED_PREVIOUS: primary only when no specific problem is described; the earlier complaints are still counted and ESC-016 still escalates the third complaint, as the Escalation Procedure 2.4 says). A subcategory can take precedence over others (FIRMWARE_UPDATE_FAILURE over HARDWARE_MALFUNCTION and DEAD_ON_ARRIVAL; REPLACEMENT_REQUEST over HARDWARE_MALFUNCTION). A demoted subcategory stays a secondary issue, and the explanation says why. Rule: the problem decides the subcategory, not the requested remedy, so REPLACEMENT_REQUEST means the replacement itself is the issue (agreed but not sent, replaced before). The definitions are shown to the GenAI in the taxonomy. Remedy keywords ("I want a replacement") were removed from REPLACEMENT_REQUEST. The dataset scenario was aligned with the definition and its 16 complaints were regenerated. Rebuilding the specs changed only one expected label (a multi-issue complaint where UNRESOLVED_PREVIOUS is now secondary). |
| **Tests performed** | 4 new tests (fallback demotion with explanation, fallback alone, precedence cases, catalog API fields, taxonomy definitions); 221 tests, all passing. Dev split, Pipeline 2 alone: all fields 84% → 88%, REPLACEMENT_REQUEST 2/11 → 9/11, FIRMWARE_UPDATE_FAILURE 2/5 → 5/5, repeats 10/15 → 14/15. One new keyword ("replacement ~ stopped working") broke 2 malfunction cases and was replaced by exact phrases. Dev sample (100, with the GenAI): subcategory 93% → 96%; the 3 targeted cases fixed, 4 other changes traced to GenAI run-to-run variation (2 of them from the missed-escalation routing safety net, recorded as a known limitation). Test split, third and final measurement: all fields 81% → 83%, subcategory 92% → 93%, department 94% → 96%, repeats 25% → 50% fully correct. The test split was measured three times in total; this is stated in `sample_complaints/README.md`. |
| **Verifying team members** | _TODO_ |
