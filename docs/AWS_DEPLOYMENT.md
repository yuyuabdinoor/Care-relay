# AWS deployment

Care Relay targets Amazon Bedrock AgentCore Runtime. The same FastAPI service
used by the local dashboard implements the AgentCore HTTP contract:

- `GET /ping`
- `POST /invocations`
- port `8080` in the deployment image

The image runs as an unprivileged user and keeps local runtime state outside the
image layer. AgentCore provides session-isolated runtime environments; an AWS
persistence adapter remains the production replacement for local SQLite.

## Prerequisites

- AWS account verification completed
- Bedrock model access in the deployment region
- AWS CLI profile with temporary, least-privilege credentials
- Node.js 20+, AWS CDK, and the AgentCore CLI
- Docker Buildx only when using the container deployment method

Avoid deploying with root-user credentials. Create a dedicated deployment role
and a separate runtime execution role.

## Recommended quick deployment

The current AgentCore CLI supports direct Python code deployment and container
deployment. Start with the production template and Python 3.12:

```bash
npm install -g @aws/agentcore
agentcore create
agentcore dev --no-browser
agentcore deploy
```

During `agentcore create`, select Strands Agents, Bedrock, and CodeZip for the
fastest hackathon iteration. Keep this repository's application modules as the
source of truth rather than accepting a second generated agent implementation.

## Container path

AgentCore container images must target ARM64:

```bash
docker buildx build --platform linux/arm64 -t care-relay:arm64 --load .
docker run --rm -p 8080:8080 --env-file .env care-relay:arm64
curl http://127.0.0.1:8080/ping
curl -X POST http://127.0.0.1:8080/invocations \
  -H 'content-type: application/json' \
  -d '{"input":{"action":"status"}}'
```

Do not bake `.env`, AWS credentials, synthetic case databases, or Strands
session files into the image.

## Runtime actions

The `/invocations` envelope accepts:

- `status`
- `process_event`
- `approve`
- `restore`

Example event payload:

```json
{
  "input": {
    "action": "process_event",
    "source": "Northside Imaging",
    "channel": "Email",
    "subject": "Appointment time updated",
    "message": "Daniel's appointment moved to Sep 11 at 2:30 PM ET."
  }
}
```

## Production follow-ons

Before handling anything beyond synthetic data:

- Replace SQLite with an encrypted AWS persistence adapter.
- Configure an AgentCore inbound authorizer.
- Give the runtime role only required Bedrock and storage permissions.
- Enable AgentCore Observability and CloudWatch Transaction Search.
- Apply log retention and redaction controls.
- Use Secrets Manager or AgentCore Identity for external credentials.
