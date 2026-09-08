# Care Relay architecture

![Care Relay system architecture](care-relay-architecture.svg)

Care Relay deliberately separates judgment, authority, and state validity. Strands
Agents decides what work to attempt and when to delegate it. Deterministic application
code decides whether dates, permissions, evidence, and state transitions are valid.

```mermaid
flowchart LR
    E["Synthetic provider event"] --> C["Strands Visit Coordinator<br/>Claude Sonnet 4.6 on Bedrock"]
    C -->|"agents-as-tools delegation"| V["Strands Verification Agent<br/>verification-only permissions"]
    C --> CT["Coordination tools<br/>transport · calendar · messaging"]
    V --> VT["Verification tools<br/>receipt check · transmission inspection"]
    CT --> D["Deterministic policy and state engine"]
    VT --> D
    D --> G["Care Relay causal dependency graph<br/>application logic, not Strands Graph"]
    D --> L["Evidence and immutable action ledger"]
    C -->|"attempt protected tool"| H["Strands HumanInTheLoop interrupt"]
    H --> U["Caregiver decision"]
    U -->|"approve or decline"| C
    D --> Q{"Every required commitment<br/>independently verified?"}
    Q -->|"No"| C
    Q -->|"Yes"| R["Visit ready"]
```

## Authority boundaries

| Concern | Authority |
|---|---|
| Interpret an external administrative message | Coordinator Agent |
| Decide which administrative tool to attempt | Coordinator Agent |
| Challenge a completion claim | Verification Agent |
| Decide whether disclosure requires approval | Deterministic policy |
| Enforce the pause before a protected tool | Strands HumanInTheLoop |
| Approve or decline the protected action | Human caregiver |
| Validate state transitions and readiness | Deterministic engine |

## Why two agents

The Verification Agent is not a second persona with equivalent access. It cannot
contact family members, schedule follow-ups, request approval, or send corrections.
Its restricted tool boundary lets it challenge the Coordinator's evidence without
quietly repairing the condition it is supposed to verify.

## Claims are not outcomes

The evidence model distinguishes `claim`, `fact`, and `verification`. A transmission
receipt proves that something was sent, not that the required recipient accepted it.
The deterministic closure gate therefore keeps a case below 100% until every required
commitment has independent verification.
