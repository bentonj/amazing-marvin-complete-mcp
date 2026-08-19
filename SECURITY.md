# Security notes

Your Marvin API tokens grant read/write access to your whole Amazing Marvin
account (the Full Access token can permanently delete data). Treat them like
passwords.

## Handling tokens

- Prefer the `*_FILE` variants (`MARVIN_API_TOKEN_FILE`, ...): keep each
  token in its own file with `chmod 600`, outside the repository, and point
  the variable at the file. Docker secrets work the same way.
- The plain environment variables (`MARVIN_API_TOKEN`, ...) are supported
  for convenience, but environment variables leak more easily (process
  listings, crash dumps, shell history when exporting inline).
- Never commit a `.env` with real values. The `.gitignore` here excludes
  `*.env`, `*token*`, `*secret*` and key files from the very first commit.

## What the server does to protect them

- Tokens are only read at startup and only sent to
  `serv.amazingmarvin.com`.
- Least privilege: the Full Access token is only attached to the endpoints
  that require it (`/doc*`, `/habits?raw=1`, reminders,
  `/resetRewardPoints`); everything else uses the limited API token.
- Logging covers method + endpoint + status, never headers or request
  bodies. `repr()` of the settings object masks all token fields.

## Running the HTTP mode

The built-in bearer check (`MCP_AUTH_TOKEN`) is a minimal internal barrier,
not a complete auth story. If you expose the server beyond localhost, put a
reverse proxy in front with TLS and real authentication (for Claude
Desktop/Web custom connectors that means OAuth — e.g. an OAuth2.1-capable
MCP auth proxy), and still keep the bearer token set so the app container
never accepts unauthenticated traffic.

## Reporting

This project is provided as-is and is not actively maintained. If you find
a security problem, feel free to open a pull request — but expect to fork
rather than wait.
