# M-Pesa STK Push Sandbox Callback Roadmap

## Goal

Verify one KodiLedger initiated Daraja sandbox STK request from initiation through callback receipt and durable webhook processing. An accepted STK request is not proof of payment, and status-query responses alone do not create KodiLedger payment or ledger records.

## Confirmed in the codebase

- The callback route is `POST /api/v1/webhooks/mpesa`.
- Callback handling checks the configured callback token and, outside `development` and `test`, the configured source IP allowlist.
- Callback IDs must match a KodiLedger recorded STK initiation before the callback is persisted and processed.
- The STK status-query endpoint does not return the payment metadata needed for financial reconciliation. Reconciliation requires the callback workflow.
- Never record Daraja passwords, consumer secrets, passkeys, callback tokens, or full tokenized callback URLs in this file or command output.

## Current checkpoint - 2026-10-05

- The user started Docker Desktop. `kodiflow_db` and `kodiflow_redis` are running, and PostgreSQL accepts connections.
- The local request table currently has `5 PENDING`, `2 SUCCEEDED`, and `2 CALLBACK_RECEIVED` records. One recent success status came from a Daraja query, not a callback; it has no payment transaction, allocation, credit, or ledger record. Refresh this snapshot before further action.
- The ngrok agent forwarded `https://trance-unstuffed-subpar.ngrok-free.dev` to local port `8001`. `docs/ngrok-callback-policy.yml` restricted the tunnel to the webhook path: public `GET /docs` returned `403`; public `GET /api/v1/webhooks/mpesa` returned `405` while the API was running.
- One callback POST reached the route and received HTTP `200`, with Daraja `ResultCode` `1037` (non-success). The database was missing the migration 0014 `locked_at` column, so the inbox row remained unprocessed. Migration 0014 was applied to the local database, and KodiLedger's non-success callback path then marked that row processed. No payment transaction, allocation, credit, or ledger entry was created for it.
- After the user confirmed the previous prompts were not received or resolved, one new KES 1 sandbox request was sent to the test number ending `9982` through local `POST /api/v1/payments/stk-push`. Daraja returned `ResponseCode` `0` (accepted for processing). Its callback was received and processed with `ResultCode` `1032` and description `Request Cancelled by user.` The callback links to no payment transaction; this was not a completed payment, and no allocation, credit, or ledger entry was created.
- The user confirmed that the latest prompt appeared on the handset. Its processed callback records a cancellation outcome, so handset delivery and the non-success callback path are confirmed; successful payment reconciliation is still unverified. To test that path, obtain authorization for a separate sandbox prompt and approve it on the handset. Do not initiate another prompt as part of this run.
- The API and ngrok processes are now stopped. The temporary process callback token was retired. Uvicorn's default access log included the callback query string, so future local runs use `--no-access-log`; never copy token-bearing inspector URLs into chat or documentation.
- The local `ngrok` command is available through the installed Microsoft Store package. Its config validates.
- Existing STK requests retain the callback URL supplied when each request was initiated. Changing `MPESA_CALLBACK_URL` now cannot retarget those requests to ngrok.
- A recent STK status query returned `ResponseCode` `0` and `ResultCode` `0`, but no corresponding callback was recorded. That query result is not sufficient to create KodiLedger accounting records.
- Do not send another STK prompt as part of this run. The newest request has a processed cancellation callback; check with the user before creating any further prompt.

## Procedure

### 1. Start local dependencies

Start Docker Desktop and wait until its engine is ready. From the repository root, start the local PostgreSQL and Redis services:

```powershell
docker compose up -d postgres redis
```

Confirm the database and Redis containers are running before proceeding. Apply pending local migrations in numeric order before starting the API. This test found that migration `0014_webhook_inbox_retries.sql` had not been applied; it was applied to the local `kodiflow_db` and adds the inbox retry columns, including `locked_at`. Keep this local development database separate from any shared or production database.

### 2. Start the ngrok tunnel

Use the installed ngrok agent or install it from the [official ngrok setup guide](https://ngrok.com/docs/getting-started/). Authenticate the agent using ngrok's setup instructions; never place its authentication token in this roadmap or in command output.

Forward the public HTTPS endpoint to local port `8001` and apply the workspace callback-only policy file:

```powershell
ngrok http 8001 --traffic-policy-file docs/ngrok-callback-policy.yml
```

Keep the tunnel running. Copy its current HTTPS forwarding origin (not the inspector address) for the next step. Confirm a public GET to `/docs` is denied by the edge policy before continuing. Avoid request history in the ngrok inspector because callback URLs contain the token.

### 3. Start KodiLedger with the current callback URL

In a separate PowerShell terminal at the repository root, set the callback URL to the current tunnel URL and run the API on port `8001`:

```powershell
$env:ENVIRONMENT = "development"
$env:DEBUG = "false"
$env:MPESA_CALLBACK_URL = "https://<current-ngrok-host>/api/v1/webhooks/mpesa"
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 48
$rng.GetBytes($bytes)
$env:MPESA_CALLBACK_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
[Array]::Clear($bytes, 0, $bytes.Length)
if ($env:MPESA_CALLBACK_TOKEN.Length -lt 32) { throw "Callback token generation failed" }
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

Replace only `<current-ngrok-host>` with the host shown by the running ngrok agent. Do not include the ngrok inspector port or put the generated callback token in this file. The app appends the process-only token to the provider callback URL and validates it. Development mode skips the source-IP allowlist for this local tunnel test; never use this setting to weaken a deployed environment. The ngrok policy exposes only the callback path, while Swagger and the STK initiation endpoint remain local. `--no-access-log` prevents Uvicorn from printing query strings that contain the callback token.

Confirm `http://127.0.0.1:8001/docs` opens. A `GET` to the callback route should return `405 Method Not Allowed`, because it accepts `POST`; this only confirms routing, not Safaricom callback delivery.

### 4. Check for an existing request before creating another

Inspect the local `stk_push_requests` table or the administrator-only unresolved STK queue. Reuse an existing unresolved app-initiated request if appropriate. Record its checkout ID privately for correlation; do not paste tokens or credentials into logs or documentation.

Existing requests retain their original callback URL; they cannot test a newly configured ngrok callback. Check unresolved requests and confirm the test phone has no outstanding prompt before creating another. After explicit confirmation to continue, submit at most one new sandbox STK request through KodiLedger Swagger at `http://127.0.0.1:8001/docs` or local `POST /api/v1/payments/stk-push`, using the confirmed test phone in `254XXXXXXXXX` format and amount. Save the returned `MerchantRequestID` and `CheckoutRequestID` outside this roadmap. `ResponseCode` equal to `0` means Daraja accepted the request; it does not mean a payment completed.

If the response is `422`, inspect request validation. For `400`, inspect app configuration. For `502`, inspect Uvicorn output for the Daraja failure. Do not retry until the first request's outcome is clear.

### 5. Verify callback delivery

- Uvicorn access logs are disabled to prevent token-bearing callback URLs from being logged. Confirm callback receipt and processing by matching the request in the local database; do not copy or share request URLs from the ngrok inspector because they contain the callback token.
- Confirm the callback's merchant and checkout IDs match the app-initiated request. A simulator-generated request with unrelated IDs is intentionally rejected.
- Confirm callback delivery from the raw inbox row correlated with the initiation IDs and its processing status. A browser GET, a status query, or the original STK acceptance response does not prove callback delivery.

### 6. Verify durable processing

For the correlated checkout ID, inspect the local database:

```sql
SELECT id, merchant_request_id, checkout_request_id,
       mpesa_receipt_number, processed, created_at
FROM raw_payment_webhooks
WHERE checkout_request_id = '<CheckoutRequestID>';
```

Check the associated `stk_push_requests` row. For a genuinely successful payment callback, verify the expected transaction and reconciliation effects. Do not send a fabricated success callback to a shared or working database; it could create financial records. If testing transport synthetically, use a non-success result and IDs from a recorded local initiation.

## Later: stable deployment

ngrok is for local development and sandbox testing; its endpoint is useful only while its tunnel is running. For a persistent callback URL, deploy the API to a hosting account you control, configure the provider callback URL and secrets there, and route the public path to this app. The public custom domain previously returned `404`; its DNS/hosting owner still needs to be identified before changing that route.
