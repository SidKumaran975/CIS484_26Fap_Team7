# Container troubleshooting record

## Test information

- Date/time and timezone:
- Tester:
- Git commit:
- Ubuntu version:
- Laptop CPU / RAM / free disk:
- Docker and Compose versions:
- Browser and client device:

## Reproduction

1.
2.
3.

- Expected result:
- Actual result:
- Exact visible error:

## Service state

Attach sanitized output from:

```bash
docker compose ps
docker compose logs --since=15m app
docker compose logs --since=15m ollama
docker stats --no-stream
df -h
free -h
```

## Diagnosis

- First failing component:
- Root cause:
- Evidence supporting the diagnosis:

## Resolution

- Commands or code changes applied:
- Result after retest:
- Follow-up work:

## Security check

Confirm the report contains no passwords, `.env` values, session cookies,
private voice samples, student recordings, or private course material.
