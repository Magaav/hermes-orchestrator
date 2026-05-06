# wasm-agent Private Configuration

`wa.env` is the machine-local security configuration for wasm-agent. It must not
be committed to the repository.

Create it from the example:

```bash
cp plugins/wasm-agent/conf/wa.env.example plugins/wasm-agent/conf/wa.env
```

Then set the only Google account allowed to create a session and the Google
Identity Services web client id:

```env
ADMIN_EMAIL=admin@example.com
GOOGLE_LOGIN_CLIENT_ID=your-google-web-client-id.apps.googleusercontent.com
```

Security rules:

- `ADMIN_EMAIL` is required. If it is absent or empty, every Google account is
  rejected.
- `GOOGLE_LOGIN_CLIENT_ID` is required for the Google sign-in button to render.
- Keep `wa.env` readable only by trusted local operators.
- Use a Google OAuth web client whose authorized JavaScript origins include the
  deployed origin, for example `https://wa.colmeio.com`.
- Public traffic should reach wasm-agent only through the HTTPS reverse proxy;
  the Python app should stay bound to `127.0.0.1`.

The server also accepts process environment overrides for deployment systems:
`HERMES_WASM_AGENT_ENV_PATH` for relocating this private env file, and
`HERMES_WASM_AGENT_GOOGLE_CLIENT_ID` for emergency client-id override. The
normal source of truth for both admin and Google client id is `wa.env`.
