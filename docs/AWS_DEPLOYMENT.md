# AWS deployment

Care Relay is deployed as a non-root container on AWS App Runner. The same
FastAPI service used by the local dashboard also implements the AgentCore HTTP
contract:

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
- A least-privilege deployment role
- Docker locally, or AWS CodeBuild for a managed container build

Avoid deploying with root-user credentials. Create a dedicated deployment role
and a separate runtime execution role.

## Current hackathon deployment

The public hackathon service uses this path:

1. AWS CodeBuild clones the public repository and builds the Dockerfile.
2. The image is pushed to a private ECR repository with scan-on-push enabled.
3. App Runner pulls the image through its ECR access role.
4. An App Runner instance role invokes the configured Bedrock model and reads one
   Google Calendar credential from Secrets Manager.
5. App Runner runs exactly one instance because this MVP uses SQLite and resumable
   local Strands session state.

No AWS credentials or Google key files are baked into the image. The deployment
uses `GOOGLE_SERVICE_ACCOUNT_JSON` as a secret-backed runtime environment value.

## Local container path

```bash
docker build -t care-relay .
docker run --rm -p 8080:8080 --env-file .env care-relay
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
