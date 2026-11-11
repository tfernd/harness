---
name: aws-cli
description: Safe AWS work - read-only first, no write to an account without the owner, explicit profile and region, and rules for Lambda, API Gateway, AI-gateway calls, IAM, SAM and CDK. Load before any `aws`, `sam` or `cdk` command, and before writing Lambda, API Gateway or IAM code or templates.
---

# AWS

No comments or docstrings: `harness:code`. Templates in Terraform: `harness:code-terraform`. Scripts: `harness:code-shell`.

## Read first, write with the owner

- Start with describe, list and get calls. They change nothing and show what exists before you propose a change.
- A write is proposed, never run on your own: create, put, update, delete, invoke, `s3 cp` or `s3 sync` to a bucket,
  and any deploy. Give the owner the exact command and what it changes (resources, region, cost, what is lost); the owner
  runs it or approves it.
- The harness guard asks before such a command; on Kiro and Cortex it blocks. A refusal is not a reason to rephrase the
  command: propose it.

## Every call

- Name `--profile` and `--region` on every call. Never rely on the default profile or the default region: a default points
  at whatever the shell last had.
- Run `aws sts get-caller-identity --profile P --region R` before the first call of a session, and say which account and
  role you are on.
- Add `--output json --no-cli-pager` when you parse the result, and `--query` to keep the output small.
- Keys never go on a command line or into a file; use a profile or the environment.

## Lambda

- Set timeout and memory explicitly; the defaults are 3 seconds and 128 MB and rarely fit.
- Make the handler idempotent: an event can arrive twice. Key the work on an id from the event.
- Configuration comes from environment variables, not code.
- A secret is never plain text in an environment variable: read it from Secrets Manager or SSM Parameter Store.
- Log structured JSON with the request id from the context.

## API Gateway

- Set throttling (rate and burst) on the stage.
- Every route has authorization; an open route is stated and justified.
- CORS allows named origins, methods and headers, not `*`.
- Validate the request (model, required parameters) at the gateway before the function runs.

## Calls through an AI gateway

- Set a connect and a read timeout on every call.
- Retry only on 429 and 5xx, with exponential backoff and jitter, a capped number of tries, and honour `Retry-After` from a gateway that sends it.
- AWS SDK calls use the SDK's own retry mode (`standard` or `adaptive`), not hand-rolled retries.
- No key in code or in the repo; read it from the environment or a secret store.
- Log the request id the gateway returns, so a failed call can be traced.
- Give each call a budget: a cap on output tokens and on spend per call or per job.

## IAM

- Least privilege: list the actions and the resource ARNs the code uses.
- A `*` in an action or a resource needs a reason written in the PR.

## SAM and CDK

- Before a deploy run `sam validate`, or `cdk synth` and `cdk diff`, and show the owner the diff.
- The owner runs `sam deploy` and `cdk deploy`; you do not.

## What no tool checks

Whether a limit (timeout, throttle, budget) fits the real load, and whether a `*` has a real reason.
