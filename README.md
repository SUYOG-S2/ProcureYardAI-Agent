# QuickDrop Rider Payout Dispute Desk

An agentic support service for delivery riders who report missing or incorrect payouts. The service receives rider messages, checks trip exports and PaySwift, explains verified results, issues small eligible payments, and sends uncertain or higher-risk cases to operations.

## Run Locally

Requirements:

- Docker Desktop with Docker Compose
- API credentials listed in `.env.example`

Create the environment file and start the complete stack:

```bash
cp .env.example .env
# Add valid OpenRouter, Mem0, and Pinecone credentials to .env
docker compose up --build
```

Services:

- Rider chat: http://localhost:8000/
- Operations dashboard: http://localhost:8000/ops
- Health check: `GET http://localhost:8000/health`
- PaySwift sandbox: http://localhost:8081

Stop the stack with:

```bash
docker compose down
```

## Public API

### Receive a rider message

```http
POST /messages
Content-Type: application/json
```

```json
{
  "message_id": "wamid.KAZ5TCF7RARUVH",
  "rider_id": "R003",
  "text": "Bhai order T926334 ka surge nahi mila",
  "received_at": "2026-09-22T09:05:00+05:30"
}
```

The response is sent back to the rider:

```json
{
  "reply": "Order T926334 ka verified difference ..."
}
```

`message_id` is the vendor message ID and is used as the idempotency key. Duplicate deliveries receive a duplicate-message response and cannot create another payout.

### Inspect operations

- `GET /trace/{rider_id}` returns the ordered message, memory, policy, AI, reconciliation, decision, and reply events.
- `GET /ops/pending` returns pending approvals and escalations.
- `POST /ops/{item_id}/approved` approves a pending payment.
- `POST /ops/{item_id}/rejected` rejects a pending item.

## Agent Design

The service is built with FastAPI, PostgreSQL, deterministic Python payout rules, and the PaySwift sandbox.

1. **Message intake:** FastAPI validates the request and PostgreSQL records the message using its vendor ID.
2. **Context gathering:** Mem0 recalls relevant rider conversation facts. Pinecone retrieves policy context when the configured policy index is available. These are best-effort context tools.
3. **AI interpretation:** OpenRouter extracts intent, dates, trip IDs, language, and confidence. The model is not trusted to calculate or authorize money.
4. **Evidence checks:** The application checks the supplied trip exports and reconciles actual amounts against PaySwift.
5. **Deterministic decision:** The calculator applies base fares, distance, surge, half-up rounding, incentives, cancellation penalties, date rules, and payment limits.
6. **Action:** Eligible shortfalls can be paid through PaySwift. Large, repeat, unclear, suspicious, stale, or failed-payment cases are added to the operations queue.
7. **Traceability:** Every important action is persisted as an ordered trace event for operator review.

## Financial Controls

- PaySwift is authoritative for paid amounts.
- The agent cannot pay more than the verified shortfall.
- Automatic payments are limited to ₹200 per dispute and once per rider per day.
- Larger or repeat payments require operations approval.
- PaySwift idempotency keys protect payout requests from duplicate delivery.
- Disputes outside the seven-day policy window are escalated.
- A PaySwift failure becomes an operations escalation instead of an unconfirmed rider success.

## Operations Workflow

Open http://localhost:8000/ops to review pending work. An operator can see why a case was queued, approve or reject eligible payments, and select a rider to inspect the complete trace. The rider-facing chat remains available at http://localhost:8000/.

## Evaluation

The evaluator is deterministic and black-box. It sends the supplied conversations through the public API, compares payout and approval deltas with `data/conversations.json`, checks required reply facts, and verifies trace completeness. It does not use an LLM judge for financial behavior.

Run it against a fresh database and fresh PaySwift sandbox:

```bash
docker compose down -v
docker compose up --build -d
python3 evals/run.py http://localhost:8000 http://localhost:8081
```

Current recorded result on 2026-10-30: **10 of 24 scenarios passed**. Local unit tests pass: **43 passed**. The evaluator still exposes end-to-end failures in payout outcomes and some multi-turn reply facts; this result should be improved before treating the project as production-ready.

## Repository Notes

- `app/`: API, agent, storage, data access, and payout logic
- `data/`: trip, payout, and conversation fixtures
- `docs/policy.md`: payout policy used by the deterministic calculator
- `evals/run.py`: black-box evaluator
- `tests/`: local regression tests
- `ai-logs/copilot-session-main.jsonl`: raw Copilot session export used during development

Do not commit `.env` or real API credentials. Use `.env.example` as the configuration template.
