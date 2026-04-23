<#outputformat "plainText">
<#assign requiredActionsText><#if requiredActions??><#list requiredActions><#items as reqActionItem>${msg("requiredAction.${reqActionItem}")}<#sep>, </#items></#list><#else></#if></#assign>
</#outputformat>
<html>
<body style="margin:0;padding:0;background:#0b1120;font-family:'Inter','Helvetica Neue',Arial,sans-serif;color:#e5e7eb;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0b1120;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#111827;border:1px solid #1f2937;border-radius:12px;overflow:hidden;">
          <tr>
            <td style="padding:28px 32px;border-bottom:1px solid #1f2937;">
              <div style="font-family:'JetBrains Mono','Menlo',monospace;letter-spacing:0.2em;font-size:12px;color:#60a5fa;text-transform:uppercase;">Agentium · Cockpit</div>
              <h1 style="margin:8px 0 0;font-size:22px;color:#f9fafb;">Action required on your account</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px;font-size:15px;line-height:1.6;color:#d1d5db;">
              <p style="margin:0 0 16px;">Hello,</p>
              <p style="margin:0 0 16px;">Your administrator has requested the following action<#if requiredActions?? && requiredActions?size gt 1>s</#if> on your Agentium account: <strong style="color:#f9fafb;">${requiredActionsText}</strong>.</p>
              <p style="margin:0 0 24px;">Click the button below to proceed. This link will expire in <strong>${linkExpirationFormatter(linkExpiration)}</strong>.</p>
              <p style="margin:0 0 24px;text-align:center;">
                <a href="${link}" style="display:inline-block;padding:12px 28px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:600;letter-spacing:0.02em;">Proceed to Agentium</a>
              </p>
              <p style="margin:0 0 8px;font-size:13px;color:#9ca3af;">If the button doesn't work, copy and paste this link:</p>
              <p style="margin:0 0 24px;font-size:13px;word-break:break-all;"><a href="${link}" style="color:#60a5fa;">${link}</a></p>
              <p style="margin:0;font-size:13px;color:#6b7280;">If you did not expect this email, you can safely ignore it — no changes will be made.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;border-top:1px solid #1f2937;font-size:12px;color:#6b7280;">
              — The Agentium team · <span style="color:#9ca3af;">noreply@datategy.net</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
