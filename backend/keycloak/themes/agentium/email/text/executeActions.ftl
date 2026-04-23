<#ftl output_format="plainText">
<#assign requiredActionsText><#if requiredActions??><#list requiredActions><#items as reqActionItem>${msg("requiredAction.${reqActionItem}")}<#sep>, </#items></#list><#else></#if></#assign>
Agentium · Cockpit

Hello,

Your administrator has requested the following action<#if requiredActions?? && requiredActions?size gt 1>s</#if> on your Agentium account: ${requiredActionsText}.

Click the link below to proceed. It will expire in ${linkExpirationFormatter(linkExpiration)}:

${link}

If you did not expect this email, you can safely ignore it.

— The Agentium team
noreply@datategy.net
