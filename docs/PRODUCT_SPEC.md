# Care Relay MVP product specification

## One-sentence pitch

Care Relay quietly coordinates the appointments, documents, and family
responsibilities created by a loved one's care, and follows each commitment
until the required outcome is independently verified.

## Primary user and track

The primary user is an unpaid family caregiver coordinating an older relative's
outpatient care. The project belongs in the Everyday Agents track.

## Demonstrated case

Daniel has an outpatient imaging appointment. His daughter Aisha is the
authorized coordinator; Marcus and Elena can provide transportation.

1. The visit begins apparently ready.
2. The imaging center moves the appointment from Thursday morning to Friday
   afternoon.
3. Care Relay invalidates Marcus's transportation commitment and the dependent
   follow-up appointment.
4. Elena accepts transportation for the new time.
5. The imaging center reports that it has not received a valid referral even
   though the clinic claimed it was sent.
6. Care Relay inspects the transmission evidence and finds that it was sent to
   general records instead of imaging.
7. Care Relay prepares a correction request and pauses for Aisha's approval.
8. After approval, the correction is sent.
9. The imaging center confirms receipt and acceptance.
10. The follow-up is rescheduled after imaging.
11. Deterministic closure rules mark the visit ready only when all four
    mandatory commitments are verified.

## Core invariant

`CLAIMED` is not `VERIFIED`.

A sender's assertion, an agent inference, or a task checkbox may establish a
claim. Only evidence from the party or system that owns the required outcome
can verify it.

## Mandatory commitments

- Appointment is confirmed for the current time.
- Transportation is accepted for that same time.
- The receiving imaging department confirms a valid referral.
- Follow-up occurs after the imaging appointment.

## Safety boundaries

- Synthetic data only.
- No diagnosis, clinical interpretation, treatment recommendation, urgency
  determination, or medication action.
- Authorization is checked deterministically.
- External messages and document sharing require action-specific approval.
- Approval is single-use and cannot authorize a different recipient or action.
- Every fact retains source, timestamp, and evidence kind.
- Agents cannot directly mark commitments verified or close a visit.

## Agent responsibilities

### Visit Coordinator

- Interpret incoming administrative messages.
- Identify affected commitments.
- Select the next permitted tool.
- Coordinate family availability.
- Replan after external changes.
- Prepare approval requests.

### Verification Agent

- Challenge unsupported completion claims.
- Compare conflicting evidence.
- Identify the missing independent confirmation.
- Recommend reopening a commitment.
- Ask the deterministic engine to evaluate readiness.

## Explicit exclusions

- Real provider or insurer integrations
- Real personal or health information
- Medication management
- Medical advice
- Billing disputes
- Voice calling
- General resource discovery
- Mobile application
- Multi-scenario support
- Autonomous contact with new organizations
- Swarm orchestration
