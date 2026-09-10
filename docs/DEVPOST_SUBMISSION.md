# Devpost submission copy

## Project name

Care Relay

## Elevator pitch

Care coordination that is not claimed complete until it is verified.

## Track

Everyday Agents

## About the project

### Inspiration

Family caregiving is full of small administrative commitments that depend on one another. If an appointment moves, the ride may no longer work, a follow-up may become invalid, and paperwork may end up at the wrong office.

The caregiver usually becomes the coordinator. They must notice every consequence, contact each organization, and decide whether “sent” really means “received.” We built Care Relay to handle that coordination quietly while keeping consequential decisions with the caregiver.

### What it does

Care Relay coordinates the commitments surrounding a loved one’s outpatient visit.

In our synthetic demonstration, an imaging provider changes Daniel’s appointment time. Care Relay interprets the message, updates the appointment, identifies the affected dependencies, finds replacement transportation inside Aisha’s approved family circle, and reschedules the follow-up within standing permission.

It also investigates a disputed referral handoff. A separately permissioned Verification Agent discovers that the referral was sent to General Records instead of the Imaging Department. Before sending a correction containing a protected identifier, Care Relay pauses and asks Aisha. After approval, the same agent run resumes, sends the narrowly scoped correction, and independently verifies receipt before declaring the visit ready.

The visit cannot reach 100% readiness merely because someone claimed a task was completed. Every required commitment needs evidence.

### How we built it

Care Relay uses **Strands Agents** with Claude through Amazon Bedrock.

A Strands Coordinator decides what work is needed and delegates disputed evidence to a separately permissioned Verification Agent through the agents-as-tools pattern. The Verifier can inspect evidence but cannot contact family members, alter schedules, or approve protected actions.

Native Strands human-in-the-loop interruption pauses execution before sensitive information is disclosed. After Aisha decides, the preserved run resumes from that boundary. Strands lifecycle hooks expose model cycles, delegation, tool execution, latency, interruptions, and completion in the dashboard while hiding sensitive argument values.

Regular application code handles the rules that should not depend on a model: permission enforcement, approval scope and consumption, date validation, dependency state, evidence classification, readiness calculation, idempotency, and the action ledger. The model can coordinate and propose actions, but it cannot grant itself permission or convert an unsupported claim into verified evidence.

The application uses FastAPI, SQLite, HTML, CSS, and JavaScript. It integrates one synthetic follow-up event with Google Calendar so the agent’s external action is visible outside Care Relay. Sessions and interruption state are persisted so approval can survive a process restart. The service also implements an AgentCore-compatible runtime contract.

### Challenges we ran into

The hardest problem was preventing apparent progress from becoming false certainty.

During testing, the model correctly said verification was pending but ended its turn before performing the verification. We strengthened the completion boundary so deterministic readiness refuses to close the visit until every mandatory commitment has independent evidence.

We also had to separate three kinds of authority: what an agent reasons should happen, what policy permits, and what external evidence confirms. That separation now exists in the code, architecture diagram, and interface.

Retries created another challenge. Model, network, and checkpoint retries can repeat a tool boundary, so external actions are idempotent. A repeated request cannot send the referral twice, reuse an approval for another action, or append duplicate evidence.

### What we learned

Agent autonomy works best when its boundaries are concrete. Our Verification Agent is not a second personality assigned to the same unrestricted model. It has a different tool boundary and cannot perform the Coordinator’s actions. Human approval is likewise enforced by code rather than left to model judgment.

We also learned that claims and verified facts need different representations. “The referral was sent” proves that somebody made a claim. It does not prove that the intended department received it.

### Potential impact

Family care coordination is not an occasional edge case. AARP and the National Alliance for Caregiving estimate that 63 million Americans—nearly one in four adults—provide ongoing care for another person. Caregivers spend an average of 27 hours each week providing care, and 24% provide at least 40 hours.

Care Relay focuses on the administrative work around care. Appointments, transportation, follow-ups, and referrals are separate commitments, but they depend on one another. When a schedule changes, the caregiver often has to discover and repair the whole chain again.

Our demonstration follows one fictional outpatient imaging visit so we can show that pattern end to end. The current MVP is imaging-specific. Its commitment, dependency, evidence, and approval model was designed to extend to other recurring workflows such as therapy appointments, equipment delivery, prescription pickup, and home-care scheduling. Those are future applications, not capabilities claimed by this submission.

The goal is not to automate medical judgment. It is to reduce coordination between providers, calendars, relatives, and administrative systems while keeping consequential actions under human control.

### What’s next

Future work would replace the remaining synthetic counterparties with consented integrations and move SQLite persistence to a managed AWS datastore. Care Relay will remain limited to administrative coordination; it will not diagnose conditions, recommend treatment, change medication, or determine medical urgency.

## Built with tags

- Strands Agents
- Amazon Bedrock
- Claude
- Python
- FastAPI
- SQLite
- Google Calendar API
- JavaScript
- HTML
- CSS
- Docker
- AWS
- AWS App Runner
- Amazon ECR
- AWS CodeBuild
- AWS Secrets Manager

## Try it out links

- Source code: https://github.com/yuyuabdinoor/Care-relay
- Demo video: ADD_PUBLIC_YOUTUBE_URL
- Live demo: https://yfbp3mfwxp.us-east-1.awsapprunner.com/

## Testing instructions

The demonstration uses only fictional people, messages, identifiers, and counterparties.

1. Open the live demo, choose **Reset demonstration**, then choose **Receive provider update**.
2. Watch the appointment change invalidate transportation and follow-up commitments.
3. Wait while the Strands Coordinator repairs permitted work and delegates the referral dispute to the restricted Verification Agent.
4. At 75% readiness, review the protected-disclosure request. Choose **Approve & send** to resume the preserved run, or **Decline** to confirm that the external correction does not execute.
5. After approval, wait for independent receipt verification and 100% readiness.
6. Expand **Inspect tool execution** to review the redacted Strands lifecycle trace.

The live reasoning path requires Amazon Bedrock. A configured Google Calendar updates one fictional follow-up event; the remaining provider and family counterparties are deterministic synthetic adapters. No medical advice is produced.

## Required uploads

- Architecture diagram: `docs/care-relay-architecture.png`
- Gallery: `docs/media/01-homepage.png`
- Gallery: `docs/media/02-human-approval.png`
- Gallery: `docs/media/03-verified-ready.png`
- Gallery: `docs/media/04-causal-ripple.png`
- Gallery: `docs/media/05-external-calendar.png`

## Disclosure

This project was created during the submission period. AI coding assistants were used for scaffolding, debugging, testing, documentation, and video editing. The runtime product uses Strands Agents and Amazon Bedrock. The demonstration narration is synthetic and was generated with ElevenLabs. All case data is synthetic.
