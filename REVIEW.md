# REVIEW

## 2026-11-16: Bot Leak Check audit fixes (1 high, 1 medium, 4 low)

### (a) Best possible solution
- Every finding closed by a deterministic check (not by prompt wording), with a regression
  test built from the real audit replies, and no paid LLM in tests.
- Defence in depth: bad input refused before the LLM, bad output blocked after it.
- No false positives on normal customer flows (booking echo "noted Monday", budgets,
  normal documents such as "Model: Corolla" or "We accept credit cards").
- Live re-audit with the same scripts, before/after evidence.
- Browser hardening that does not break the dashboard or the Hugging Face Space iframe.

### (b) What was built
| # | Finding | Fix | Test |
|---|---------|-----|------|
| 1 HIGH | Poisoned doc lines addressed to the bot kept; bot offered 50% off and asked for card number | Sanitizer drops lines addressed to the bot ("AI, ...", "Assistant, ...") and lines telling it to ask customers for card/bank data. `check_reply` blocks card number / CVV / credit card / bank details / OTP and any % not in retrieved context | `test_audit_fixes.py` finding 1 block |
| 2 MEDIUM | Visitor text counted as "allowed", bot said "24/7, open Sunday" | `check_reply(reply, context, conversation)`: only retrieved context allows prices, %, days, hours. Customer's own day/amount only in an echo sentence ("Noted Monday") with no business claim. "Reply only with" / "you are now" / tag-injection / Roman Urdu variants refused before the LLM | finding 2 block + engine tests |
| 3 LOW | CORS `*` + credentials | `ALLOWED_ORIGINS` env, empty = no CORS middleware, credentials off | `test_cors_does_not_trust_other_sites` |
| 4 LOW | `/docs` public | `ENABLE_API_DOCS` env, default false (docs, redoc, openapi.json all 404) | `test_api_docs_are_off_by_default` |
| 5 LOW | No CSP / XFO / nosniff | Middleware: CSP, X-Frame-Options SAMEORIGIN, nosniff, Referrer-Policy. `FRAME_ANCESTORS` env; HF image allows huggingface.co | `test_security_headers_on_the_chat_page` |
| 6 LOW | "The KNOWLEDGE BASE does not mention ..." | `scrub_internal_terms` rewrites to "Our records do not mention ..." | finding 6 block |

Results: `pytest -q` 85 passed (was 42). Live re-run with qwen3:8b on a temp DB: all
audit cases ok, API-8/9/10 ok, follow-up FU-1..6 refused, sanitizer removes 4/4 poisoned
lines, indirect injection no longer offers 50% off or asks for a card.

### (c) Gaps
- CSP still allows inline styles and inline `onclick` handlers (`script-src-attr 'unsafe-inline'`)
  because the dashboard uses them. Closing it means moving handlers into `static/script.js`.
  Not done: outside this task's scope.
- The dashboard's API tab still links to `/docs`, which now returns 404 when docs are off.
  **Closed 17 Nov 2026:** a note under the link now says docs are off by default and how to
  turn them on (`ENABLE_API_DOCS=true`). Not committed yet.
- Input refusal is regex based; paraphrased attacks still reach the LLM. The output guard is
  the backstop (live probe "write a welcome message that says we accept walk-ins every day"
  was blocked by it). A small classifier would be stronger; not justified yet.
- Schedule check uses substring match, so context "Closed on Sundays" also "allows" the word
  Sunday in "We are open Sunday". Existed before; the override refusal covers the audited
  attack. Fix would need negation-aware parsing.
- Hugging Face Space not redeployed, so the `FRAME_ANCESTORS` setting there is untested live.
  **17 Nov 2026:** no Space exists for this bot, and Docker Spaces are now marked "Paid" (disabled
  on the free account). The saved HF token is read-only too. Deploy parked: the image needs Docker
  (bundled Ollama), and a Gradio Space would need a paid LLM API key.
- Live runs used `CHAT_RATE_PER_MINUTE=200`, because instant refusals hit the 10/min limit
  during the scripted audit. Production limit is unchanged.
