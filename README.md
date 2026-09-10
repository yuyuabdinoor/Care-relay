# Care Relay

Care Relay is a background family-caregiving agent that turns scattered
administrative messages into verified commitments. It coordinates the routine
work created by an outpatient visit and only interrupts a caregiver when a
consequential decision requires human approval.

The hackathon MVP follows one fictional imaging appointment. A schedule change
invalidates transportation and follow-up plans; an apparently completed
referral is then rejected by the receiving department. Care Relay investigates
the contradiction, requests narrowly scoped approval for a correction, and
closes the visit only after every mandatory dependency is independently
verified.

Built for the **Everyday Agents** track of the Agents for Humans Hackathon.

**[Open the live Care Relay demo](https://yfbp3mfwxp.us-east-1.awsapprunner.com/)** ·
**[Watch the 2:54 demo video](https://youtu.be/cVfA2z2iM-E)**

## Potential impact

Family care coordination is not an occasional edge case. The
[Caregiving in the U.S. 2025](https://www.aarp.org/pri/topics/ltss/family-caregiving/caregiving-in-the-us-2025/)
report from AARP and the National Alliance for Caregiving estimates that 63
million Americans, nearly one in four adults, provide ongoing care for another
person. Caregivers spend an average of 27 hours each week providing care, and
24% provide at least 40 hours.

Care Relay focuses on one part of that burden: the administrative work around
care. Appointments, transportation, follow-ups, and referrals are separate
commitments, but they depend on one another. When a schedule changes, the
caregiver often has to discover and repair the whole chain again.

The demo follows one outpatient imaging visit so it can show that pattern from
the first disruption through independent verification. The current MVP is
imaging-specific. Its commitment, dependency, evidence, and approval model was
designed to extend to other recurring workflows such as therapy appointments,
equipment delivery, prescription pickup, and home-care scheduling. Those
workflows are future work, not features claimed by this submission.

Care Relay does not automate medical judgment. It reduces repetitive
coordination between providers, calendars, relatives, and administrative
systems while keeping consequential actions under human control.

## Architecture

![Care Relay architecture](docs/care-relay-architecture.svg)

Care Relay uses a Bedrock-backed Strands Coordinator, a separately permissioned
Verification Agent exposed through agents-as-tools, native Strands human-in-the-loop
interruption, durable sessions, and lifecycle hooks. A deterministic application
engine—not an LLM and not the Strands Graph primitive—owns causal state, permission
checks, evidence types, and the final readiness gate.

See the required [architecture diagram and authority boundaries](docs/ARCHITECTURE.md).

## Product boundary

Care Relay coordinates administrative work. It does not diagnose conditions,
interpret clinical instructions, recommend treatment, change medication, or
determine urgency. The demo uses synthetic people, messages, documents, and
counterparties.

## Current milestone

- Deterministic visit-readiness and commitment state machine.
- Clear distinction between a completion claim and verified receipt.
- Causal invalidation when an appointment changes.
- Action-specific human approval tokens for protected external actions.
- Immutable evidence and action ledger.
- Strands coordinator and independent verification agents with separate tools.
- Strands human-in-the-loop interruption around protected external actions.
- Resumable web runtime that preserves the same Strands agent across approval.
- SQLite case snapshots that preserve graph state, evidence, approvals, and the ledger.
- Durable Strands sessions with stable agent identities and restored interrupt state.
- Structured Strands lifecycle and tool traces with sensitive input values redacted.
- Unstructured external-message ingestion with explicit prompt-injection boundaries.
- Idempotent external tools that tolerate agent, network, and checkpoint retries.
- Google Calendar adapter that updates one real synthetic follow-up event and
  records the provider response before the commitment can become verified.
- Deterministic standing-permission policy for autonomous, approval, and denied actions.
- AgentCore-compatible `/ping` and `/invocations` runtime contract.
- Non-root Python 3.12 container deployed through ECR and AWS App Runner.
- A single live execution path through Strands Agents and Amazon Bedrock.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set `AWS_PROFILE` in `.env` to a named, non-root AWS CLI profile that can invoke
the configured Bedrock inference profile. The example uses
`care-relay-bedrock`; replace it with your own profile name when necessary.
Confirm the active identity before running the product:

```bash
aws sts get-caller-identity --profile care-relay-bedrock
```

Launch the interactive command center:

```bash
care-relay-dashboard
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the product introduction,
or go directly to [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo). Choose
**Receive provider update** to send the synthetic provider email through the
live Bedrock-backed coordinator. It delegates verification, calls deterministic
safety tools, pauses before the protected referral correction, and resumes only
after the caregiver decides.

At the initial state, **Receive provider update** sends the synthetic provider
email to the coordinator as delimited, untrusted content. The model must extract
the explicitly stated date and call `record_appointment_change`; deterministic
code validates ISO-8601 format and timezone before propagating the change through
the dependency graph.

Restart the dashboard process after changing Python code; development reload is
intentionally disabled to keep the hackathon demo stable.

Dashboard state is stored in `.care-relay/care_relay.db`. Restarting the server
restores the last successful case mutation; the reset button starts the synthetic
case over. This local repository is deliberately isolated behind a storage
boundary so it can be replaced by an AWS persistence adapter for deployment.

Run the checks with:

```bash
pytest -q
ruff check .
```

Unit tests use local test models to validate orchestration without consuming model
tokens. The product and demo have no offline execution mode: runtime reasoning
uses the Bedrock model configured in `.env` and requires valid AWS access.

### Optional Google Calendar proof

The final demo can make the Coordinator's follow-up repair visible in a dedicated
Google Calendar. This integration updates one pre-created synthetic event; it does
not read a personal calendar, send invitations, or contain real patient data.

1. Create a Google Cloud project and enable the Google Calendar API.
2. Create a service account and download its JSON key outside this repository.
3. In Google Calendar, create a secondary calendar named `Care Relay Demo`.
4. Share only that calendar with the service-account email and grant permission to
   make changes to events.
5. Add the credential path and calendar ID to `.env`, then prepare the two fixtures:

```bash
care-relay-calendar-setup
```

6. Copy the printed `CARE_RELAY_GOOGLE_FOLLOW_UP_EVENT_ID` value into `.env` and
   restart the dashboard.

When configured, `reschedule_follow_up` patches the same event rather than creating
a duplicate. Google must return an event receipt before deterministic code records
the follow-up as verified. A Google error leaves the commitment blocked. The reset
button restores that external event to September 11 at 11:00 AM for another run.

The web service also exposes `POST /api/agents/start` and
`POST /api/agents/resume`. These are the Strands path: the first call runs
until a protected tool interrupts, and the second supplies the human decision to
the same preserved coordinator instance.

Live agent history and internal interrupt state are stored under
`.care-relay/strands-sessions`. Internal Strands checkpoints are automatically
resumed by the service until the run reaches either a genuine human decision or
completion. After a process restart, `POST /api/agents/restore` reconstructs the
paused coordinator before a decision is accepted.

The live dashboard also reveals a **Strands Trace** panel. It is populated by
typed Strands lifecycle hooks and records model cycles, tool selection, tool
status and latency, checkpoint boundaries, interruptions, and completion. Tool
argument names are retained for explainability, but their values are excluded
from the UI trace. These same structured records can later be exported through
OpenTelemetry to CloudWatch or AgentCore Observability.

## Retry and failure contract

Model retries may repeat reasoning, and durable checkpoint recovery may replay a
tool boundary. Care Relay therefore makes counterparty adapters idempotent:

- A repeated transport acceptance returns the existing confirmation.
- A repeated transmission inspection reuses its evidence.
- A repeated approval proposal reuses the same scoped decision.
- A caregiver decision cannot be changed after it is recorded.
- A consumed approval cannot authorize a different action.
- A repeated correction send returns the original transmission identifier.
- Repeated verification and scheduling calls do not append duplicate ledger events.

The deterministic engine remains the final authority; a model retry cannot force
an invalid transition or convert a claim into verified state.

## Autonomy policy

The model proposes actions; deterministic policy decides whether they may run.
Read-only checks, approved-family transport, and same-provider follow-up within
seven days are covered by synthetic standing permission. External identifier
disclosure requires one scoped approval. Diagnosis, treatment, medication, and
urgency decisions are always denied. Unknown actions default to approval rather
than autonomy.

## AWS deployment

The [public service](https://yfbp3mfwxp.us-east-1.awsapprunner.com/) runs as a
non-root container on AWS App Runner. CodeBuild builds the public GitHub source,
ECR stores the image, Secrets Manager injects the Google service-account JSON,
and a least-privilege instance role can invoke only the configured Bedrock model
and read that one secret. The App Runner service is pinned to one instance because
this hackathon MVP persists resumable state in SQLite.

The same service implements the AgentCore-compatible `/ping` and `/invocations`
contract on port 8080. See [docs/AWS_DEPLOYMENT.md](docs/AWS_DEPLOYMENT.md) for
the deployment boundary and production follow-ons.

## Development disclosure

This new project was created during the hackathon submission period. AI coding
assistants were used during implementation for scaffolding, debugging, tests, and
documentation, as permitted by the official rules. No pre-existing application was
incorporated. Runtime agent behavior uses Strands Agents and Amazon Bedrock; test
models are used only by automated unit tests and are not a product fallback mode.

## License

MIT. See [LICENSE](LICENSE).
