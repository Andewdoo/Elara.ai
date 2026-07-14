# AWS Side-Project Demo Deployment

This filename is retained because existing links and the CloudFormation stack use the former `public-beta` name. The current goal is a personal, low-traffic side-project demo, not a public beta or production SaaS.

Use [DEPLOYMENT.md](DEPLOYMENT.md) as the authoritative runbook and [DEMO_SCOPE.md](../DEMO_SCOPE.md) as the scope authority.

The accepted topology is intentionally small:

- one Vercel frontend;
- one AWS EC2 host for API, worker, PostgreSQL/pgvector, Redis, and supporting containers;
- one private AWS S3 evidence bucket;
- one HTTPS API hostname;
- no high availability, multi-AZ, autoscaling, separate staging/production environment, formal on-call, or public-launch certification.

Historical Step 25 evidence in `STAGING_VALIDATION_25B_EVIDENCE.md` can be used to understand the host's current state, but its former release bars no longer block a demo.
