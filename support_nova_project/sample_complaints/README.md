# SupportNova synthetic complaint dataset

500 fictional customer complaints for Lumora Home Technologies, each with its expected labels
(SRS section "Complaint Dataset"). There are no real customers, orders or personal data in it.

## Files

| File | What it contains |
|---|---|
| `complaint_specs.csv` | What every complaint is about, and its expected labels, decided **before** any text was written |
| `generated_text.jsonl` | The text the LLM wrote for each spec, with token counts and any check failures |
| `complaints.csv` | **The dataset**: spec + expected labels + complaint text (open it in Excel) |
| `evaluation/` | Results of `evaluate_dataset` (one CSV row per complaint + a JSON summary) |

## How it was made (approach C: Python decides, the LLM only writes)

1. **Specs** (`build_dataset_specs`). Python code picks the scenario of each complaint:
   the subcategory or subcategories, the product, the customer type, the channel, the order facts
   (days late, days since delivery or purchase, amount), extra details (for example "burning smell"
   or "legal action"), the writing style and the length.
   - The **expected labels** are the Complaint Resolution Rule Matrix applied to that true scenario.
   - Core complaints are built per resolution rule. Random facts that satisfy the rule are drawn, and a
     draw is kept only if the matrix really selects that rule, so no more specific rule overrides it.
   - Fixed seed, so the same specs are produced on every run.
2. **Text** (`generate_complaint_text`). DeepSeek writes each complaint from its spec.
   - It uses a separate prompt and client, not Pipeline 1, and it never sees the expected labels.
   - Every text is checked: length; order-number placeholder; no invented numbers; no extra
     escalation trigger that would change the labels; near-duplicates must not be identical copies.
   - A failed check is retried once with a hint. Anything still wrong is flagged for human review.
   - Prompt-injection payloads are inserted by code, word for word.
3. **Load** (`load_dataset`). Each complaint is submitted through the normal intake service.
   - Dataset customers are named `ds_c0001` and so on.
   - Each order is dated so that the facts the system calculates are exactly the spec's facts.
   - Repeats reuse the original order.
4. **Evaluate** (`evaluate_dataset`). The system is scored against the expected labels. It reports
   Pipeline 2 alone, Pipeline 1 alone and the final decision.

```
python manage.py build_dataset_specs
python manage.py generate_complaint_text          # needs DEEPSEEK_API_KEY
python manage.py load_dataset
python manage.py evaluate_dataset --pipeline python --split all
python manage.py evaluate_dataset --pipeline full --split test
```

## Groups

| Group | Count | What it tests |
|---|---|---|
| core | 279 | 2–4 complaints per reachable resolution rule |
| escalation | 40 | one escalation trigger each (legal, regulator, media, chargeback, vulnerable customer, no heating, theft, fraud, GDPR, recall, high value...) |
| multi_issue | 26 | two or three issues in one complaint |
| difficult_policy | 25 | facts exactly on a rule boundary (5/6 and 10/11 days late, 7/8, 14/15, 30/31 days, 365/366 and 1095/1096 days), or the customer cites an outdated or wrong policy (FAQ voucher, old 14-day refund policy) |
| prompt_injection | 24 | 12 different attacks at 4 positions (start, middle, end, supporting information) |
| repeat | 19 | the same issue raised again in new words (8 chains of 3, 3 chains of 2) |
| incomplete | 15 | no order, no dates |
| calm_critical | 12 | a hazard mentioned calmly and in passing inside another complaint |
| ambiguous | 12 | no clear category: the right outcome is a human review |
| contradictory | 12 | the customer's claims contradict the order record ("it arrived yesterday", but the order says 20 days) |
| policy_exception | 12 | asks for an exception outside a policy window |
| unsupported_refund | 12 | demands a refund or compensation that no rule allows |
| near_duplicate | 12 | the same complaint sent again, lightly reworded |

Also, 20 customers have a second, **unrelated** complaint, which must not be linked as a repeat.
The mix covers simple, emotional, high- and low-priority, security, privacy and safety complaints.
`build_dataset_specs` prints the counts against the SRS minimums.

## Split

**100 complaints are held out as the unseen test set** (`split = test`). This is about 20% of every group, and linked complaints are always kept together.
- Tune thresholds, keywords and prompts on `dev` only.
- Report results on `test`.

## Expected-label columns

`expected_category`, `expected_subcategory`, `expected_secondary`, `expected_department`,
`expected_supporting`, `expected_urgency`, `expected_priority`, `expected_escalation`,
`expected_escalation_rules`, `expected_rule`, `expected_compensation` (allowed compensation),
`expected_review_required`.

## Known limitations

- **Shared rule logic.** Expected labels reuse the rule engine's combination logic: most specific
  rule wins, every escalation rule applies. That logic has its own unit tests. The dataset tests
  whether the system *understands* complaints: classification, facts and triggers.
- **Model bias.** The same model family (DeepSeek) writes the complaints and analyses them in
  Pipeline 1. This may make GenAI accuracy look slightly better than it would be on real complaints.
- **Rules not covered.** Two rules cannot be targeted from order data: RR-030 and RR-053 use
  `days_late` for refund and repair delays. The no-condition fallbacks RR-107 to RR-113 apply only
  when facts are missing, and are covered by the incomplete group.
- **Extra triggers.** An extra trigger that the checks judged harmless can be present in the text.
  An example is "it gave me a shock" in an electric-shock complaint. It is not in
  `expected_escalation_rules`, but it does not change any expected label.

## Results (test split, 100 unseen complaints)

Tuning was done on the dev split only. The test split was measured three times: before tuning,
after the first tuning round (keywords, injection patterns, duplicate thresholds, prompt v1.3), and
after the overlap fix (subcategory definitions for UNRESOLVED_PREVIOUS, HARDWARE_MALFUNCTION,
FIRMWARE_UPDATE_FAILURE and REPLACEMENT_REQUEST). Each measurement is a single GenAI run, so
differences of 1-2 points are within run-to-run variation.

| | Before | Round 1 | Round 2 (final) |
|---|---|---|---|
| Final result, all six fields correct | 72% | 81% | 83% |
| Final subcategory correct | 89% | 92% | 93% |
| Final department correct | 92% | 94% | 96% |
| Final priority correct | 93% | 96% | 96% |
| Final escalation level correct | 84% | 93% | 93% |
| Pipeline 2 alone, all fields / subcategory | 58% / 60% | 75% / 77% | 78% / 79% |
| Pipeline 1 (GenAI) alone, subcategory / priority | 89% / 63% | 92% / 60% | 93% / 60% |
| Injection attempts flagged at intake / by GenAI | 1/5, 5/5 | 5/5, 5/5 | 5/5, 5/5 |
| Repeats / duplicates: linked, type correct | 7/7, 4/7 | 7/7, 7/7 | 7/7, 7/7 |
| Complaints sent to manual review | 69% | 58% | 59% |
| GenAI errors caught by review / reached the final result unreviewed | - | 74.5% / 3 | 74% / 2 |
| Unnecessary reviews (GenAI completely right) | - | 12 | 15 |

Reading the numbers:
- The GenAI understands complaints well (93% subcategory) but sets priority and escalation by its
  own judgement (60% / 80%). The final result takes those from the rule matrix. This is the
  two-pipeline design working as intended.
- Most manual reviews are justified: they catch a GenAI error, or the complaint needs a person
  (ambiguous, incomplete, manipulation, compliance). The SRS requires a review when the pipelines disagree.
- The injection intake result is optimistic: the test payloads are the same 12 types as in dev.
- Remaining confusions: UNEXPECTED_RENEWAL vs CANCELLATION_ISSUE (3), POOR_COMMUNICATION vs
  UNRESOLVED_PREVIOUS in follow-ups chosen by the GenAI (2).
- When the GenAI misses an escalation, the safety-net routing gives the complaint to the
  escalation's department. That is right for safety, but in 2 dev cases it moved a billing complaint
  to Customer Relations or Management.

Dataset changes during tuning:
- The REPLACEMENT_REQUEST scenario was aligned with the new catalog definition (the replacement
  itself is the issue, not a new fault), and its 16 complaints were regenerated.
- One multi-issue expected label changed, because UNRESOLVED_PREVIOUS is now a fallback.

Details: `evaluation/test_full.json` / `.csv`. The earlier runs are `test_full_before_tuning.*` and `test_full_after_tuning1.*`.
