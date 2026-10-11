# Email deliverability — `datategy.net` (Agentium transactional)

Actionable checklist for making sure Keycloak emails (reset password,
verify email, MFA) reliably land in the user's inbox when sent via
`ssl0.ovh.net:465` from `noreply@datategy.net`.

## 1. Current DNS state (audited 2026-04-23)

```
SPF       v=spf1 include:spf.mailjet.com include:mx.ovh.com include:_spf.google.com ~all
DMARC     v=DMARC1; p=quarantine; pct=90; sp=none
MX        aspmx.l.google.com. (Google Workspace)
DKIM      no selector found for ovhmo1, mail, default, selector1, selector2, ovh
```

Assessment:

- **SPF**: OK. `include:mx.ovh.com` already authorizes `ssl0.ovh.net`
  to send on behalf of `datategy.net`.
- **DMARC**: `p=quarantine; pct=90` — strict. 90% of mails that fail
  SPF-or-DKIM alignment will land in spam/quarantine. Sends without
  DKIM alignment are at real risk.
- **DKIM**: **missing**. No selector is published. OVH sends our
  transactional mail unsigned → DMARC alignment fails → high spam
  probability.
- **MX on Google**: unrelated to sending, but worth noting: inbound
  mail is on Google Workspace, so any internal test to
  `*@datategy.net` will be received via Google's spam filtering (which
  is stricter than most).

## 2. What to do

### 2.1 Activate DKIM in OVH for `noreply@datategy.net` (required)

1. OVH manager → **Web Cloud** → **Emails** → `datategy.net` →
   **DKIM** tab.
2. Generate a DKIM key (OVH suggests a selector, typically
   `ovhmo1` or similar).
3. OVH prints a DNS record to publish. Add it to the DNS zone for
   `datategy.net`:

   ```
   Name:   <selector>._domainkey.datategy.net
   Type:   TXT
   TTL:    3600
   Value:  v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQ...  (provided by OVH)
   ```

4. Wait ~5-15 min for DNS propagation, then go back to OVH and click
   **Verify / Activate**. OVH will start signing outgoing mail.
5. Validate from the VM:

   ```bash
   dig +short TXT <selector>._domainkey.datategy.net
   ```

   Should return the `v=DKIM1; k=rsa; p=...` record.

### 2.2 Confirm end-to-end delivery

Send a test mail and inspect the raw headers on the receiving side:

- `Authentication-Results:` should show `spf=pass`, `dkim=pass`,
  `dmarc=pass` after DKIM is live.
- Until DKIM is live, `dmarc=fail` with `quarantine` action is
  expected → mail goes to spam.

If still in spam after DKIM is live:

- Check the `From:` matches `noreply@datategy.net` exactly (no
  display-name tricks).
- Verify the TLS handshake on port 465 is SSL/TLS wrapped (not
  STARTTLS) — that matches our current realm config.

### 2.3 Optional hardening

- Publish a DMARC `rua` reporting address to get real-world delivery
  feedback:

  ```
  _dmarc.datategy.net TXT
    v=DMARC1; p=quarantine; pct=100; sp=quarantine;
    rua=mailto:dmarc-reports@datategy.net;
    ruf=mailto:dmarc-reports@datategy.net;
    adkim=r; aspf=r
  ```

- Consider moving transactional mail to a dedicated provider
  (SendGrid / Mailjet / SES / Postmark) once customer volume grows.
  Pros: better deliverability, bounce/open tracking, DKIM managed for
  you, sub-account reputation isolated from our mailbox reputation.

## 3. Where this is wired in the stack

- `backend/keycloak/realm-export.json` holds non-sensitive SMTP
  settings (host, port, ssl, from, displayName). `user` and `password`
  are intentionally absent.
- `backend/keycloak/bootstrap-smtp.sh` patches `smtpServer.user` and
  `smtpServer.password` after import, using env vars `SMTP_USER` and
  `SMTP_PASSWORD`.
- Email theme is under
  `backend/keycloak/themes/agentium/email/` and mounted into the
  container via `deploy/redeploy-keycloak.sh`. Realm fields
  `emailTheme` / `loginTheme` / `accountTheme` are set to `agentium`.

## 4. Lower DMARC temporarily? (not recommended)

If DKIM cannot be set up quickly and emails must go out anyway, one
can temporarily soften DMARC to `p=none; rua=...` to collect reports
without enforcing quarantine. **Do not leave it in `p=none` long-term**
— it exposes the domain to spoofing.
