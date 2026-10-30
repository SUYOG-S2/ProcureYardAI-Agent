# Rider Payout Dispute Desk

Project by **Suyog Gouda**.

## Run
Copy `.env.example` to `.env`, add the required OpenRouter, Mem0 and Pinecone values, then run `docker compose up --build`. The rider chat is at `http://localhost:8000/`; the ops dashboard is `http://localhost:8000/ops`. Health: `GET /health`.

Run the evaluation with `python3 evals/run.py http://localhost:8000 http://localhost:8081`. Set `PAYSWIFT_BASE_URL` or pass a second argument when PaySwift is not at `http://localhost:8081`.

## Design
FastAPI receives WhatsApp messages and uses `wamid` as the idempotency key. Postgres stores complete messages, traces, queue items and decisions. CSV exports provide trip facts; PaySwift is authoritative for actual payouts. The deterministic calculator applies IST dates, Decimal half-up rounding, trip fares, incentives and cancellation penalties. It alone decides verified shortfalls and payment limits.

OpenRouter extracts structured intent and entities. Mem0 stores searchable rider conversation facts. Pinecone retrieves policy context. These AI systems can interpret and recall context but cannot authorize money or replace trip/PaySwift evidence. Missing, mismatched, suspicious, repeat and over-limit claims enter the ops queue. Approved amounts are sent to PaySwift with an idempotency key.

## Inspecting the agent
Open `http://localhost:8000/` for the rider chat and `http://localhost:8000/ops` for the ops dashboard. The ops page shows pending approvals/escalations and lets an operator select a rider to inspect the ordered trace: incoming message, memory/policy/AI calls, deterministic reconciliation, decision, and reply. The same trace is available as JSON from `GET /trace/{rider_id}`. Pending work is available from `GET /ops/pending`.

## Evaluation method
This project uses a **deterministic black-box rubric**, not an LLM-as-judge score for financial behavior. The evaluator sends the supplied conversations through only the public service interface, reads PaySwift's payout ledger, reads the pending-ops queue, and checks each scenario for:

- HTTP success for every rider message
- Exact payout delta and approval delta against `data/conversations.json`
- Required facts in the rider-facing replies
- Required `message_in` and `reply` trace events
- Duplicate-message and safety outcomes through the same public interfaces

The system should be reset to a fresh database and fresh PaySwift sandbox before a full run, as required by the assignment. Human-in-the-loop is a product control for large/repeat payments, not the evaluator: operators approve or reject queue items in the dashboard. LLM output is not trusted to judge money; exact expected values and PaySwift are the oracle.

## Assumptions and limits
The supplied exports are loaded at startup and represent the trip system for this exercise. Rider IDs are normalized for known export variants such as `003`, `R7` and `R007`. Disputes older than seven days are escalated. AI credentials are required by configuration; Mem0 recall and Pinecone policy retrieval are best-effort context tools and cannot authorize money. The evaluator should be run against a fresh database and PaySwift sandbox, as specified by the assignment. The raw Copilot session export used during development is included in `ai-logs/copilot-session-main.jsonl`.

## Validation
Local validation: `43 passed` with `/usr/local/bin/python3 -m pytest -q`.

Fresh-stack black-box evaluation on 2026-10-30: `10/24 scenarios passed` using `/usr/local/bin/python3 evals/run.py http://localhost:8000 http://localhost:8081`. The evaluator exposed remaining end-to-end failures in payout outcomes and some reply facts; this score must improve before submission.
