# Railway deployment

`railway.ts` declares the production backend service and its persistent data volume.

After committing and pushing the application changes:

1. Create an empty Railway project and install the Railway CLI.
2. Run `railway login`, then `railway link` from the repository root.
3. Run `railway config plan` and review the proposed backend service and volume.
4. Run `railway config apply` and confirm the plan.
5. Generate a public Railway domain for the `backend` service.

The service builds `backend/Dockerfile` from the `backend` source root. Its SQLite database and temporary session media are stored on the `/data` volume in Railway's Singapore region. The configured CORS origin is the GitHub Pages host, `https://sumirankc.github.io`.
