#!/usr/bin/env python3
"""One-shot writer for backend/app/resources/flows/nawa_password_reset_v1.json.

Emits the committed artifact: the LLM flow, its 100% simulated twin (same
topology, LLM nodes turned into canned-output pass-throughs) and the System
settings that carry the scenario presets + simulated directory constants.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

OUT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "resources"
    / "flows"
    / "nawa_password_reset_v1.json"
)

ASSISTANT = "NAWA WE"

# --------------------------------------------------------------------------
# Prompts. The instruction block of each prompt is IDENTICAL across the three
# scenario presets — only the caller's verbatim words / the collected evidence
# change. Rendering them here (instead of hand-copying them into the presets)
# is what guarantees we are not steering the model per scenario.
# --------------------------------------------------------------------------
INTENT_PROMPT = f"""You are {ASSISTANT}, the IT service desk workspace engine for Nawa.
Classify the service desk request below into exactly one category.

Allowed categories (output the identifier only, lower case, nothing else):
password_reset - the requester knows their account but cannot remember the password and asks for a reset
unlock_ad_account - the account exists and is locked out, typically after repeated failed sign-in attempts
password_expiry - the password has expired or is about to expire and must be renewed
other - anything else

Request received by the service desk (verbatim, any language):
"{{transcript}}"

Answer with one identifier from the list above and nothing else."""

IDENTITY_PROMPT = f"""You are {ASSISTANT}, the IT service desk workspace engine for Nawa.
Decide whether the identity evidence below satisfies the Nawa ITSD policy for a privileged password reset.

Policy: a reset may be performed without human approval only when at least two independent proofs are present,
and one of them must be either a line-manager confirmation or a staff ID checked against the HR record.
Security questions alone are never sufficient. Never assume evidence that is not listed.

Evidence collected by the agent:
{{evidence}}

Answer on a single line starting with exactly one of these two tokens:
IDENTITY_VERIFIED - the policy is satisfied
IDENTITY_INSUFFICIENT - the policy is not satisfied and a human approval is required
Then add one short sentence justifying the token."""

NOTICE_PROMPT = f"""You are {ASSISTANT}, the IT service desk workspace engine for Nawa.
Write the message the service desk sends to the requester once the password has been reset.

Constraints:
- English first, then the same message in Arabic.
- Say that a temporary password has been issued and must be changed at the first sign-in.
- The temporary password is: Nawa-Temp-7431
- Include the mandatory security warning: the service desk never asks for a password, and the temporary
  password must not be shared with anyone.
- Maximum 90 words per language. No markdown, no signature block.

Requester: {{requester}}"""


def preset(
    *,
    label: str,
    channel: str,
    requester_name: str,
    requester_upn: str,
    transcript: str,
    evidence: str,
    evidence_items: list,
    preferred_language: str,
    received_at: str,
    subject: str,
    simulated_intent: str,
    simulated_identity_verdict: str,
    simulated_user_message: str,
) -> dict:
    return {
        "label": label,
        "channel": channel,
        # Queue metadata. The business app lists these cases as the requests
        # waiting at the service desk, so it needs what a queue shows — arrival
        # time and the triaged subject — and NOT the ``label`` above, which
        # names the test case rather than the ticket. No ticket reference here
        # on purpose: the closure emits its own, and a reference invented for
        # the queue would contradict the one the run reports.
        "received_at": received_at,
        "subject": subject,
        "requester_name": requester_name,
        "requester_upn": requester_upn,
        "preferred_language": preferred_language,
        "request_text": transcript,
        "identity_evidence": evidence,
        # The artefacts the agent actually FILED, one string per verifiable
        # item. This is the evidence record the grounding check reads, and it
        # is deliberately not the same thing as the narrative above: a caller
        # can state a staff ID without anything being recorded against it.
        "evidence_items": list(evidence_items),
        "intent_prompt": INTENT_PROMPT.replace("{transcript}", transcript),
        "identity_prompt": IDENTITY_PROMPT.replace("{evidence}", evidence),
        "notice_prompt": NOTICE_PROMPT.replace("{requester}", requester_name),
        # Canned outputs, read ONLY by the fully simulated fallback flow.
        "simulated_intent": simulated_intent,
        "simulated_identity_verdict": simulated_identity_verdict,
        "simulated_user_message": simulated_user_message,
        "simulated_evidence_count": len(evidence_items),
    }


SCENARIO_PRESETS = {
    "nominal": preset(
        label="Case A - forgotten password, complete identity evidence",
        channel="phone_call",
        requester_name="Hassan Al-Mansouri",
        requester_upn="hassan.almansouri@nawa.qa",
        transcript=(
            "I forgot my password, can you reset it? I cannot sign in to my laptop this morning."
        ),
        evidence=(
            "- Staff ID 40219 read out by the caller and matched against the HR record by the agent.\n"
            "- Line manager Fatima Al-Sayed confirmed the request by phone at 08:42.\n"
            "- Two security questions answered correctly."
        ),
        evidence_items=[
            "Staff ID 40219 matched against HR record HR-40219 by agent M. Kaabi at 08:39.",
            "Line-manager confirmation from Fatima Al-Sayed, call reference CALL-2026-0729-0311.",
            "Security questions 2/2 correct, answers logged against ticket ITSD-2026-0729-0148.",
        ],
        preferred_language="en",
        # Before 08:39, when the agent matched the staff ID against HR below.
        received_at="08:34",
        subject="Cannot sign in - password forgotten",
        simulated_intent="password_reset",
        simulated_identity_verdict=(
            "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the "
            "request, so two independent proofs are present."
        ),
        simulated_user_message=(
            "Your Nawa account password has been reset. A temporary password has been issued: "
            "Nawa-Temp-7431. Sign in with it and you will be asked to choose a new password "
            "immediately. The service desk never asks you for your password: do not share this "
            "temporary password with anyone.\n\n"
            "\u062a\u0645 \u0625\u0639\u0627\u062f\u0629 \u062a\u0639\u064a\u064a\u0646 \u0643\u0644\u0645\u0629 "
            "\u0645\u0631\u0648\u0631 \u062d\u0633\u0627\u0628\u0643 \u0641\u064a \u0646\u0648\u0627. "
            "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0627\u0644\u0645\u0624\u0642\u062a\u0629: "
            "Nawa-Temp-7431. \u0633\u062c\u0644 \u0627\u0644\u062f\u062e\u0648\u0644 \u0628\u0647\u0627 "
            "\u0648\u0633\u064a\u064f\u0637\u0644\u0628 \u0645\u0646\u0643 \u0627\u062e\u062a\u064a\u0627\u0631 "
            "\u0643\u0644\u0645\u0629 \u0645\u0631\u0648\u0631 \u062c\u062f\u064a\u062f\u0629 \u0641\u0648\u0631\u0627\u064b. "
            "\u0645\u0643\u062a\u0628 \u0627\u0644\u062e\u062f\u0645\u0629 \u0644\u0627 \u064a\u0637\u0644\u0628 "
            "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631 \u0623\u0628\u062f\u0627\u064b: "
            "\u0644\u0627 \u062a\u0634\u0627\u0631\u0643\u0647\u0627 \u0645\u0639 \u0623\u062d\u062f."
        ),
    ),
    "ambiguous": preset(
        label="Case B - the caller says reset, the symptom says lockout",
        channel="phone_call",
        requester_name="Youssef Benali",
        requester_upn="youssef.benali@nawa.qa",
        transcript=(
            "mon compte est bloque depuis ce matin, j'ai tape trois fois et maintenant ca ne "
            "veut plus rien savoir, il faut me remettre le mot de passe"
        ),
        evidence=(
            "- Caller states their name and department.\n"
            "- No staff ID provided.\n"
            "- No line-manager confirmation obtained."
        ),
        evidence_items=[
            "Caller self-declared name and department, nothing checked against a record.",
        ],
        preferred_language="fr",
        received_at="08:47",
        # Triaged from the symptom the caller describes, not from what they ask
        # for: the subject must not pre-empt the classification the agent makes.
        subject="Cannot sign in after repeated attempts",
        simulated_intent="unlock_ad_account",
        simulated_identity_verdict=(
            "IDENTITY_INSUFFICIENT Only a self-declared name was provided."
        ),
        simulated_user_message="",
    ),
    "weak_identity": preset(
        label="Case C - legitimate request, insufficient identity evidence",
        channel="email",
        requester_name="Layla Haddad",
        requester_upn="layla.haddad@nawa.qa",
        transcript=(
            "Hi, I need my password reset please. I am travelling and cannot come to the office."
        ),
        evidence=(
            "- Caller states their name and department.\n"
            "- No staff ID provided and none could be matched against the HR record.\n"
            "- No line-manager confirmation obtained.\n"
            "- One security question answered correctly."
        ),
        evidence_items=[
            "Security question 1/1 correct, logged against ticket ITSD-2026-0729-0148.",
        ],
        preferred_language="en",
        received_at="09:02",
        subject="Password reset request - requester travelling",
        simulated_intent="password_reset",
        simulated_identity_verdict=(
            "IDENTITY_INSUFFICIENT Only one security question was answered and neither a staff ID "
            "nor a line-manager confirmation is available."
        ),
        simulated_user_message=(
            "Your Nawa account password has been reset after supervisor approval. A temporary "
            "password has been issued: Nawa-Temp-7431. Sign in with it and you will be asked to "
            "choose a new password immediately. The service desk never asks you for your password: "
            "do not share this temporary password with anyone."
        ),
    ),
    "ad_unreachable": preset(
        label="Case D - clean request, the automation bridge to the directory is down",
        channel="walk_in",
        requester_name="Omar Al-Kuwari",
        requester_upn="omar.alkuwari@nawa.qa",
        transcript=(
            "Good morning, I cannot remember my password since the holiday. Could you reset it "
            "for me please? My laptop is with me."
        ),
        evidence=(
            "- Staff ID 51884 read from the badge and matched against the HR record at the desk.\n"
            "- Line manager Khalid Al-Thani confirmed the request in person.\n"
            "- Photo ID checked at the walk-in desk."
        ),
        evidence_items=[
            "Staff ID 51884 matched against HR record HR-51884 at the walk-in desk at 09:15.",
            "Line-manager confirmation from Khalid Al-Thani, in person, witnessed by the desk agent.",
            "Photo ID checked at the walk-in desk, badge scan BSCAN-2026-0729-0077.",
        ],
        preferred_language="en",
        # Before 09:15, when the badge was scanned at the desk below.
        received_at="09:11",
        subject="Password reset at the walk-in desk",
        simulated_intent="password_reset",
        simulated_identity_verdict=(
            "IDENTITY_VERIFIED Badge staff ID matched the HR record and the line manager confirmed "
            "the request in person, so two independent proofs are present."
        ),
        simulated_user_message=(
            "Your Nawa account password has been reset. A temporary password has been issued: "
            "Nawa-Temp-7431. Sign in with it and you will be asked to choose a new password "
            "immediately. The service desk never asks you for your password: do not share this "
            "temporary password with anyone."
        ),
    ),
    "quality_guard": preset(
        label="Case E - the assessment says verified, the evidence record is empty",
        channel="phone_call",
        requester_name="Noura Al-Emadi",
        requester_upn="noura.alemadi@nawa.qa",
        transcript=(
            "Hello, I need my password reset. My staff ID is 60312 and my manager already "
            "approved it, he told me he would call you."
        ),
        # Two proofs are ASSERTED, so a reasonable model reads the policy as
        # satisfied. Nothing was filed against them, which is precisely what the
        # grounding check catches on the lane where no human is in the loop.
        evidence=(
            "- Staff ID 60312 stated by the caller.\n"
            "- Caller reports that line manager Ahmed Al-Kubaisi has approved the request.\n"
            "- Caller answered the department question correctly."
        ),
        evidence_items=[],
        preferred_language="en",
        received_at="09:26",
        subject="Password reset request",
        simulated_intent="password_reset",
        simulated_identity_verdict=(
            "IDENTITY_VERIFIED A staff ID and a line-manager approval were both reported, so the "
            "policy appears satisfied."
        ),
        simulated_user_message="",
    ),
}

# --------------------------------------------------------------------------
# Typed-request lane.
#
# The five presets above are canned cases. This block is what the business app
# needs to hand the flow a request somebody types in front of an audience.
#
# It has to carry the prompt TEMPLATES, placeholders included, because the
# assembly cannot happen inside the run: the walker resolves node inputs by
# reference and composes no strings, and the model skill takes a single
# ``prompt`` with no separate instruction channel. So the app substitutes the
# caller's words the same way this generator does for the presets - against the
# same three constants, not against copies of them, which is what keeps a typed
# request and a preset request judged by an identical instruction block.
#
# The defaults exist so the composer opens pre-filled: the point of the lane on
# stage is to edit them - remove an evidence line and watch the gate open - not
# to type three fields from scratch.
# --------------------------------------------------------------------------
FREE_TEXT = {
    "label": "Request typed at the service desk",
    "channel": "service_desk_form",
    "requester_name": "Sara Al-Naimi",
    "requester_upn": "sara.alnaimi@nawa.qa",
    "preferred_language": "en",
    "intent_prompt_template": INTENT_PROMPT,
    "identity_prompt_template": IDENTITY_PROMPT,
    "notice_prompt_template": NOTICE_PROMPT,
    "default_request_text": (
        "I forgot my password and I cannot sign in this morning. Could you reset it please?"
    ),
    "default_identity_evidence": (
        "- Staff ID 44807 read out by the caller and matched against the HR record by the agent.\n"
        "- Line manager Aisha Al-Marri confirmed the request by phone.\n"
        "- Two security questions answered correctly."
    ),
    "default_evidence_items": [
        "Staff ID 44807 matched against HR record HR-44807 by the desk agent.",
        "Line-manager confirmation from Aisha Al-Marri, logged against the ticket.",
        "Security questions 2/2 correct, answers logged against the ticket.",
    ],
    # A pasted document would push the instruction block out of the model's
    # attention and cost minutes on stage. The app truncates at this length.
    "max_request_chars": 600,
    # Read only by the fully simulated twin, exactly like the presets': on that
    # flow every model call is canned, so a typed request is echoed back with
    # these instead of being classified.
    "simulated_intent": "password_reset",
    "simulated_identity_verdict": (
        "IDENTITY_VERIFIED Staff ID matched the HR record and the line manager confirmed the "
        "request, so two independent proofs are present."
    ),
    "simulated_user_message": (
        "Your Nawa account password has been reset. A temporary password has been issued: "
        "Nawa-Temp-7431. Sign in with it and you will be asked to choose a new password "
        "immediately. The service desk never asks you for your password: do not share this "
        "temporary password with anyone."
    ),
}

SIMULATION = {
    "directory": "Nawa corporate directory (simulated)",
    "directory_reset": {
        "operation": "reset_user_password",
        "target_directory": "Nawa corporate directory (simulated)",
        "performed_by": f"{ASSISTANT} service account (simulated)",
        "mode": "dry_run",
        "result": "success",
        "note": "No directory is contacted. This step records the privileged gesture it would perform.",
    },
    "temporary_password_issued": "Nawa-Temp-7431",
    "force_change_at_next_logon": True,
    "password_policy": "12 characters minimum, 1 uppercase, 1 digit, 1 symbol, no reuse of the last 10",
    "ticket": {
        "id": "ITSD-2026-0729-0148",
        "queue": "End User Support",
        "state": "closed",
        "resolution": (
            "Password reset completed, temporary password issued, requester guided to set a new "
            "password at first sign-in."
        ),
    },
    # Payload handed to the automation bridge. The bridge is a REAL platform
    # connector skill (rpa_dispatch_v1); it is not configured for this
    # workspace, so the dispatch genuinely fails and the incident lane is a
    # real traced failure rather than a staged one.
    "directory_bridge": {
        "job_key": "nawa_directory_password_reset",
        "timeout_s": 10,
        "input": {
            "operation": "reset_user_password",
            "target_directory": "Nawa corporate directory (simulated)",
        },
    },
    # Canned failure record used ONLY by the fully simulated twin, which binds
    # no connector at all.
    "directory_bridge_failure": {
        "_status": "failed",
        "_error": "Automation bridge to the directory is not reachable from this workspace.",
    },
    "closed_by": f"{ASSISTANT} (simulated)",
    # What an auditor actually needs to prove is not only what the platform
    # did, but what it PREVENTED. A silence proves nothing: these two records
    # state that a privileged write was authorised, withheld, and why, with the
    # account left untouched. Same editorial rule as the outcome messages — no
    # component is ever named in a compliance record.
    "audit_withheld": {
        "incident": {
            "event_type": "itsd.password_reset.withheld",
            "details": {
                "action": "reset_user_password",
                "disposition": "withheld",
                "account_modified": False,
                "temporary_password_issued": False,
                "requester_notified": False,
                "withheld_reason": (
                    "The reset was authorised after a successful identity check, but the Nawa "
                    "corporate directory did not accept the request. Nothing was applied to the "
                    "account and the ticket remains open for the manual directory procedure."
                ),
                "target_directory": "Nawa corporate directory (simulated)",
                "ticket_id": "ITSD-2026-0729-0148",
                "mode": "dry_run",
                "assistant": ASSISTANT,
                "use_case": "UC-01 Password Reset",
            },
        },
        "quality_hold": {
            "event_type": "itsd.password_reset.withheld",
            "details": {
                "action": "reset_user_password",
                "disposition": "withheld",
                "account_modified": False,
                "temporary_password_issued": False,
                "requester_notified": False,
                "withheld_reason": (
                    "The identity assessment concluded that the requester was identified, but "
                    "fewer than the two independent proofs Nawa ITSD policy requires were on file "
                    "for an unattended privileged reset, so the reset was held before any change "
                    "was made to the account."
                ),
                "target_directory": "Nawa corporate directory (simulated)",
                "ticket_id": "ITSD-2026-0729-0148",
                "mode": "dry_run",
                "assistant": ASSISTANT,
                "use_case": "UC-01 Password Reset",
            },
        },
    },
    "audit_event_type": "itsd.password_reset.completed",
    "audit_details": {
        "action": "reset_user_password",
        "target_directory": "Nawa corporate directory (simulated)",
        "ticket_id": "ITSD-2026-0729-0148",
        "mode": "dry_run",
        "assistant": ASSISTANT,
        "use_case": "UC-01 Password Reset",
    },
}

# Every outcome carries the same three customer-facing fields - code, label,
# message - so the surface has one rule and never has to fall back on a
# technical string to have something to display. `message` is the sentence the
# service desk would say to a human; nothing in it names a component, a
# connector, a parameter or a provider. Anything technical belongs to the
# `diagnostic_*` keys of the sink payload and to the execution trace.
OUTCOMES = {
    "closed": {
        "code": "ticket_closed",
        "label": "Ticket closed",
        "message": (
            "The account password was reset and a temporary password was issued to the "
            "requester, who must change it at the next sign-in. The ticket is closed and the "
            "action is recorded in the audit ledger."
        ),
        "reset_performed": True,
    },
    "routed": {
        "code": "routed_to_other_use_case",
        "label": "Routed to another ITSD use case - no reset performed",
        "message": (
            "This request is not a password reset: the account is locked out after repeated "
            "failed sign-in attempts. It has been routed to the account unlock procedure and no "
            "password was changed."
        ),
        "reset_performed": False,
        "target_use_case": "Account unlock (UC-02)",
    },
    "refused": {
        "code": "approval_refused",
        "label": "Human approval refused - no privileged action taken",
        "message": (
            "The supervisor refused the reset for this requester. No password was changed and no "
            "temporary password was issued. The requester must present stronger proof of "
            "identity before the request can be reconsidered."
        ),
        "reset_performed": False,
    },
    "incident": {
        "code": "incident_directory_unreachable",
        "label": "Incident - the directory could not be reached, no reset performed",
        # Deliberately says what happened to the REQUEST, not what happened to
        # a piece of software. A service desk manager reads this line and knows
        # the state of the account without knowing what a connector is.
        "message": (
            "The reset was authorised but could not be applied: the Nawa corporate directory did "
            "not accept the request. The account was not modified, no temporary password was "
            "issued and the requester was not notified. The ticket stays open and the request can "
            "be applied through the manual directory procedure."
        ),
        "reset_performed": False,
        "remediation": (
            "Relaunch the same request through the manual directory procedure: the reset then "
            "completes without going through the automated route."
        ),
        # Structured so the surface can build the retry action from data rather
        # than from a sentence, and so no input parameter has to be spelled out
        # in prose the customer reads.
        "replay_input": {"scenario": "ad_unreachable", "bridge_fallback": True},
    },
    "quality_hold": {
        "code": "quality_hold_ungrounded_assessment",
        "label": "Held for review - the filed evidence does not meet the identity rule",
        # A governance decision, phrased as one. Nothing here reads as a
        # malfunction, because nothing malfunctioned. Accurate at zero proofs and
        # at one, since the rule is about how many are on file either way.
        "message": (
            "The reset was held before any change was made. The assessment concluded that the "
            "requester was identified, but Nawa ITSD policy requires at least two independent "
            "proofs on file before an unattended privileged reset, and fewer were recorded. The "
            "account was not modified. File the missing proof, or route the request to a "
            "supervisor for approval."
        ),
        "reset_performed": False,
        "remediation": (
            "File the evidence the caller asserted (HR match, line-manager confirmation), then "
            "re-run. Nothing was written to the directory."
        ),
    },
}

# The grounding check asks the platform evaluator to score the identity
# assessment against the evidence actually filed. Only `context_count` gates
# the flow: it is computed from the payload, so the gate stays deterministic
# even if the embedding backend degrades (the evaluator then returns zeroed
# scores, which are reported but never block).
QUALITY_QUESTION = (
    "Is the identity of the requester established by verifiable evidence on file, as required "
    "by the Nawa ITSD policy for an unattended privileged password reset?"
)


def ref(node_id: str, *path: str) -> dict:
    return {"node_id": node_id, "path": list(path)}


def port(name: str, schema: str) -> dict:
    return {"name": name, "schema": schema}


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------
def case_node(nid: str, preset_key: str, label: str, description: str, x: int, y: int) -> dict:
    return {
        "id": nid,
        "type": "simulation",
        "kind": "task",
        "label": label,
        "position": {"x": x, "y": y},
        "data": {"menu": "Simulation bench", "description": description},
        "config": {
            "runtime_ref": "builtin:passthrough",
            "inputs_map": {"case": ref("system", "scenario_presets", preset_key)},
            "outputs_map": {"case": "intake.case"},
        },
        "inputs": [],
        "outputs": [port("case", "object")],
    }


NODES = [
    {
        "id": "source.request",
        "type": "source",
        "kind": "source",
        "label": "Service desk request (call \u00b7 email \u00b7 walk-in)",
        "position": {"x": 40, "y": 460},
        "data": {
            "menu": "Entry",
            "description": (
                "Run input. Carries the scenario to inject on the simulation bench "
                "(nominal | ambiguous | weak_identity | ad_unreachable | quality_guard), or "
                "free_text plus a whole 'case' object for a request typed in the business app."
            ),
        },
        "config": {},
        "inputs": [],
        "outputs": [port("scenario", "string"), port("case", "object")],
    },
    {
        "id": "decision.case_selector",
        "type": "decision",
        "kind": "decision",
        "label": "Simulation bench \u00b7 which inbound case",
        "position": {"x": 340, "y": 460},
        "data": {
            "menu": "Simulation bench",
            "description": (
                "Selects WHICH request the service desk receives - never what the agent decides "
                "about it. Each branch loads one canned caller case (verbatim words + identity "
                "evidence collected) from the System settings; the classification and the identity "
                "assessment downstream are real model calls on that payload. Unknown or absent "
                "scenario falls back to the nominal case. The ad_unreachable_bypass branch loads "
                "the same caller case as ad_unreachable but leaves the automation bridge out of "
                "the run: it is the remediation path an operator takes after the incident. The "
                "free_text branch takes the case from the run input instead of the settings, for "
                "a request typed in the business app; everything downstream of it is identical."
            ),
        },
        "config": {
            "branches": [
                # First: it is the only branch whose case does not come from the
                # settings, so an unknown scenario must not reach it by accident.
                {"label": "free_text", "condition": "scenario == 'free_text'"},
                {
                    "label": "ad_unreachable_bypass",
                    "condition": "scenario == 'ad_unreachable' and bridge_fallback == True",
                },
                {"label": "ad_unreachable", "condition": "scenario == 'ad_unreachable'"},
                {"label": "quality_guard", "condition": "scenario == 'quality_guard'"},
                {"label": "ambiguous", "condition": "scenario == 'ambiguous'"},
                {"label": "weak_identity", "condition": "scenario == 'weak_identity'"},
                {"label": "nominal", "condition": "scenario == 'nominal'"},
            ],
            "default_branch": "nominal",
            "inputs_map": {
                "scenario": ref("run", "scenario"),
                "bridge_fallback": ref("run", "bridge_fallback"),
            },
        },
        "inputs": [port("scenario", "string"), port("bridge_fallback", "boolean")],
        "outputs": [port("chosen_branch", "string")],
    },
    case_node(
        "task.case_nominal",
        "nominal",
        "Case A \u00b7 Forgotten password, complete evidence",
        "Canned inbound case: the requester asks for a reset and the agent collected a matched "
        "staff ID, a line-manager confirmation and two security questions.",
        640,
        260,
    ),
    case_node(
        "task.case_ambiguous",
        "ambiguous",
        "Case B \u00b7 'Reset my password' after three failed sign-ins",
        "Canned inbound case: the requester asks for a reset but describes a lockout after "
        "repeated failed sign-in attempts. Tests whether the agent discriminates instead of "
        "guessing.",
        640,
        460,
    ),
    case_node(
        "task.case_weak_identity",
        "weak_identity",
        "Case C \u00b7 Legitimate request, weak identity evidence",
        "Canned inbound case: a plausible reset request with no staff ID and no line-manager "
        "confirmation. Tests the governance gate before any privileged write.",
        640,
        660,
    ),
    case_node(
        "task.case_ad_unreachable",
        "ad_unreachable",
        "Case D \u00b7 Clean request, automation bridge down",
        "Canned inbound case: a walk-in request with complete, filed evidence. The identity "
        "assessment passes; what fails is the automation bridge to the directory. Tests that an "
        "infrastructure incident is traced and contained instead of half-applied.",
        640,
        860,
    ),
    case_node(
        "task.case_quality_guard",
        "quality_guard",
        "Case E \u00b7 Confident assessment, empty evidence record",
        "Canned inbound case: the caller asserts a staff ID and a manager approval, so the "
        "assessment reads the policy as satisfied - but nothing was filed against either claim. "
        "Tests that an ungrounded assessment cannot authorise an unattended privileged write.",
        640,
        1060,
    ),
    {
        # The only case node fed by the run rather than by the settings. The app
        # assembles the case from the FREE_TEXT templates and posts it whole, so
        # the eight fields the lanes downstream read keep the exact same names
        # and the graph after this node is untouched.
        "id": "task.case_free_text",
        "type": "simulation",
        "kind": "task",
        "label": "Typed request \u00b7 case supplied by the business app",
        "position": {"x": 640, "y": 1260},
        "data": {
            "menu": "Simulation bench",
            "description": (
                "Inbound case typed by an operator in the business app: verbatim words, requester "
                "and collected evidence come from the run input, and the prompts were assembled "
                "from the templates in the System settings before the run started. Nothing here "
                "decides the outcome - the classification and the identity assessment downstream "
                "are the same real model calls the preset lanes run."
            ),
        },
        "config": {
            "runtime_ref": "builtin:passthrough",
            "inputs_map": {"case": ref("run", "case")},
            "outputs_map": {"case": "intake.case"},
        },
        "inputs": [],
        "outputs": [port("case", "object")],
    },
    {
        "id": "task.classify_intent",
        "type": "llm",
        "kind": "task",
        "label": "Step 1 \u00b7 Classify the request (model call)",
        "position": {"x": 960, "y": 460},
        "data": {
            "menu": "Reasoning",
            "description": (
                "REAL inference. Reads the caller's verbatim words and returns ONE identifier from "
                "a closed enum (password_reset | unlock_ad_account | password_expiry | other). The "
                "output is constrained to the enum so nothing can drift on screen, and the prompt "
                "instruction block is identical for every scenario preset."
            ),
        },
        "config": {
            "skill_slug": "azure_llm_v1",
            "skill_id": None,
            "inputs_map": {
                "prompt": ref("intake", "case", "intent_prompt"),
                "model": ref("system", "default_model"),
            },
            "outputs_map": {"completion": "intake.intent"},
        },
        "inputs": [port("prompt", "string"), port("model", "string")],
        "outputs": [port("completion", "string"), port("model", "string")],
    },
    {
        "id": "decision.intent_route",
        "type": "decision",
        "kind": "decision",
        "label": "Step 1 \u00b7 Intent routing",
        "position": {"x": 1280, "y": 460},
        "data": {
            "menu": "Control",
            "description": (
                "Only a password_reset classification enters the reset procedure. Anything else - "
                "including an unreadable classification, since 'other_use_case' is the default "
                "branch - leaves the flow with no privileged action attempted. One entry door "
                "covers the adjacent account-unlock and password-expiry use cases."
            ),
        },
        "config": {
            "branches": [
                {"label": "password_reset", "condition": "'password_reset' in intent"},
                {
                    "label": "other_use_case",
                    "condition": (
                        "'unlock_ad_account' in intent or 'password_expiry' in intent "
                        "or 'other' in intent"
                    ),
                },
            ],
            "default_branch": "other_use_case",
            "inputs_map": {"intent": ref("intake", "intent")},
        },
        "inputs": [port("intent", "string")],
        "outputs": [port("chosen_branch", "string")],
    },
    {
        "id": "sink.routed_elsewhere",
        "type": "sink",
        "kind": "sink",
        "label": "Outcome \u00b7 Routed to another ITSD use case",
        "position": {"x": 1600, "y": 200},
        "data": {
            "menu": "Outcome",
            "description": (
                "Terminal leaf. The request left the password-reset procedure with the detected "
                "intent and its justification: no identity assessment, no directory write, no "
                "ticket closed."
            ),
        },
        "config": {
            "inputs_map": {
                "outcome": ref("system", "outcomes", "routed"),
                "detected_intent": ref("intake", "intent"),
                "request_text": ref("intake", "case", "request_text"),
            }
        },
        "inputs": [port("outcome", "object"), port("detected_intent", "string")],
        "outputs": [],
    },
    {
        "id": "task.verify_identity",
        "type": "llm",
        "kind": "task",
        "label": "Step 2 \u00b7 Assess the identity evidence (model call)",
        "position": {"x": 1600, "y": 520},
        "data": {
            "menu": "Reasoning",
            "description": (
                "REAL inference. Weighs the evidence the agent collected against the Nawa ITSD "
                "policy (two independent proofs, one of them a line-manager confirmation or a "
                "matched staff ID) and must ABSTAIN explicitly - IDENTITY_INSUFFICIENT - rather "
                "than assume. Abstention is what opens the human gate."
            ),
        },
        "config": {
            "skill_slug": "azure_llm_v1",
            "skill_id": None,
            "inputs_map": {
                "prompt": ref("intake", "case", "identity_prompt"),
                "model": ref("system", "default_model"),
            },
            "outputs_map": {"completion": "identity.verdict"},
        },
        "inputs": [port("prompt", "string"), port("model", "string")],
        "outputs": [port("completion", "string"), port("model", "string")],
    },
    {
        "id": "decision.identity_gate",
        "type": "decision",
        "kind": "decision",
        "label": "Step 2 \u00b7 Identity verdict",
        "position": {"x": 1920, "y": 520},
        "data": {
            "menu": "Control",
            "description": (
                "Fail-safe router. IDENTITY_VERIFIED proceeds; anything else that the assessment "
                "actually produced goes to the human gate. It has NO default branch on purpose: "
                "when the assessment never ran (the request was routed away at step 1) both "
                "branches stay closed, which is how the whole reset procedure downstream is "
                "neutralised."
            ),
        },
        "config": {
            "branches": [
                {
                    "label": "verified",
                    "condition": "'IDENTITY_VERIFIED' in identity_verdict",
                },
                {
                    "label": "insufficient",
                    "condition": (
                        "identity_verdict != None and identity_verdict != '' "
                        "and 'IDENTITY_VERIFIED' not in identity_verdict"
                    ),
                },
            ],
            "inputs_map": {"identity_verdict": ref("identity", "verdict")},
        },
        "inputs": [port("identity_verdict", "string")],
        "outputs": [port("chosen_branch", "string")],
    },
    {
        "id": "hitl.identity_gate",
        "type": "policy",
        "kind": "hitl",
        "label": "Step 2b \u00b7 Human approval before a privileged reset",
        "position": {"x": 2240, "y": 760},
        "data": {
            "menu": "Governance",
            "description": (
                "Durable gate. The run pauses in hitl_pending, a Decision is created and the "
                "operator approves or refuses it in the platform's own screen (run detail, inbox "
                "or the Flow Builder). Nothing privileged is written before that verdict, and who "
                "approved and when stays in the ledger. TTL policy is configured here: 1 day, "
                "refuse on expiry."
            ),
        },
        "config": {
            "prompt": (
                "Identity evidence is insufficient for an automated password reset. Approve the "
                "privileged reset (simulated) for this requester?"
            ),
            "approvers": ["operator", "itsd_supervisor"],
            "expires_in_days": 1,
            "expiry_action": "reject",
            "inputs_map": {
                "requester": ref("intake", "case", "requester_name"),
                "requester_account": ref("intake", "case", "requester_upn"),
                "request_text": ref("intake", "case", "request_text"),
                "identity_evidence": ref("intake", "case", "identity_evidence"),
                "identity_verdict": ref("identity", "verdict"),
            },
        },
        "inputs": [port("requester", "string"), port("identity_verdict", "string")],
        "outputs": [port("approved", "boolean"), port("decision_id", "string")],
    },
    {
        "id": "task.directory_bridge",
        "type": "connector",
        "kind": "task",
        "label": "Step 3a \u00b7 Dispatch the reset to the automation bridge",
        "position": {"x": 2240, "y": 1060},
        "data": {
            "menu": "Directory",
            "description": (
                "REAL platform connector (rpa_dispatch_v1). This is the only node that reaches "
                "outside the platform, and the bridge is not provisioned for this workspace, so "
                "the dispatch fails for real: the trace carries a failed invocation with the "
                "provider's own error, not a staged one. Only the ad_unreachable lane attempts it."
            ),
        },
        "config": {
            "skill_slug": "rpa_dispatch_v1",
            "skill_id": None,
            "inputs_map": {
                "job_key": ref("system", "simulation", "directory_bridge", "job_key"),
                "input": ref("system", "simulation", "directory_bridge", "input"),
                "timeout_s": ref("system", "simulation", "directory_bridge", "timeout_s"),
            },
            "outputs_map": {
                "_status": "directory.bridge_status",
                "_error": "directory.bridge_error",
                "job_key": "directory.bridge_job",
            },
        },
        "inputs": [port("job_key", "string"), port("input", "object")],
        "outputs": [port("status", "string")],
    },
    {
        "id": "task.quality_gate",
        "type": "analysis",
        "kind": "task",
        "label": "Step 2c \u00b7 Grounding check on the identity assessment",
        "position": {"x": 2240, "y": 340},
        "data": {
            "menu": "Governance",
            "description": (
                "REAL platform evaluator (response_eval_v1), the same primitive the observability "
                "screens read. It scores the assessment against the evidence actually FILED and "
                "counts those items. Only the count gates the flow, so the guard stays "
                "deterministic even if the scoring backend degrades; the scores travel to the "
                "outcome for the quality dashboard. It runs on the verified lane only - the lane "
                "where no human would otherwise look at the decision."
            ),
        },
        "config": {
            "skill_slug": "response_eval_v1",
            "skill_id": None,
            "inputs_map": {
                "answer": ref("identity", "verdict"),
                "query": ref("system", "quality_gate", "question"),
                "context_chunks": ref("intake", "case", "evidence_items"),
            },
            "outputs_map": {
                "context_count": "quality.evidence_count",
                "composite": "quality.score",
                "hallucination_rate": "quality.hallucination_rate",
            },
        },
        "inputs": [port("answer", "string"), port("context_chunks", "array")],
        "outputs": [port("composite", "number"), port("context_count", "number")],
    },
    {
        "id": "decision.execute_reset",
        "type": "decision",
        "kind": "decision",
        "label": "Step 2b \u00b7 Authorisation to execute",
        "position": {"x": 2560, "y": 600},
        "data": {
            "menu": "Control",
            "description": (
                "Single authorisation point for every privileged gesture. Four ways out, checked "
                "in this order: the automation bridge failed, so nothing can be applied; the "
                "assessment is not grounded in any filed evidence, so it must not run unattended; "
                "the requester is verified or a human approved; a human refused. When none of them "
                "holds the branch set is empty and all five execution steps below are skipped - "
                "that is what makes 'no reset performed' verifiable in the trace rather than "
                "asserted."
            ),
        },
        "config": {
            "branches": [
                {"label": "incident", "condition": "bridge_status == 'failed'"},
                # The published policy: "identity is established when at least two
                # independent proofs are on file". So the threshold is the
                # policy's, not a nominal non-zero check — a staff number the
                # caller read out is one proof, and an UNATTENDED privileged
                # reset on it alone is exactly what the rule forbids. The
                # assessment model does state IDENTITY_VERIFIED on a single
                # proof, which is why this is enforced here and not in a prompt.
                #
                # "Fewer than two" is spelled as the two values rather than as
                # `< 2`, and that is not a style choice: the predicate evaluator
                # evaluates every operand of an `and` before combining them
                # (run_engine/condition.py), so a guarded `evidence_on_file !=
                # None and evidence_on_file < 2` still runs the ordered
                # comparison and fails the whole run on every lane where the
                # quality node did not execute and the count is absent. Equality
                # against a missing value is safe; ordering is not.
                #
                # `human_approved != True` because a supervisor's approval makes
                # the write attended, which is the case this rule is not about:
                # their decision carries the account, under their name, in the
                # ledger. Without it, approving a thin request at the gate would
                # be silently overruled here.
                {
                    "label": "quality_hold",
                    "condition": (
                        "(evidence_on_file == 0 or evidence_on_file == 1) "
                        "and human_approved != True"
                    ),
                },
                {
                    "label": "execute",
                    "condition": "identity_branch == 'verified' or human_approved == True",
                },
                {"label": "refused", "condition": "human_approved == False"},
            ],
            "inputs_map": {
                "identity_branch": ref("decision.identity_gate", "chosen_branch"),
                "human_approved": ref("hitl.identity_gate", "approved"),
                "bridge_status": ref("directory", "bridge_status"),
                "evidence_on_file": ref("quality", "evidence_count"),
            },
        },
        "inputs": [
            port("identity_branch", "string"),
            port("human_approved", "boolean"),
            port("bridge_status", "string"),
            port("evidence_on_file", "number"),
        ],
        "outputs": [port("chosen_branch", "string")],
    },
    {
        "id": "task.ad_reset",
        "type": "simulation",
        "kind": "task",
        "label": "Step 3 \u00b7 Reset the account in the directory (simulated)",
        "position": {"x": 2880, "y": 220},
        "data": {
            "menu": "Directory",
            "description": (
                "SIMULATED privileged gesture. No directory is contacted: the step records, in "
                "dry-run semantics, the operation it would perform, on which account, under which "
                "authorisation."
            ),
        },
        "config": {
            "runtime_ref": "builtin:passthrough",
            "inputs_map": {
                "directory_action": ref("system", "simulation", "directory_reset"),
                "target_account": ref("intake", "case", "requester_upn"),
                "requester": ref("intake", "case", "requester_name"),
                "authorisation": ref("decision.execute_reset", "chosen_branch"),
            },
            "outputs_map": {
                "directory_action": "directory.reset",
                "target_account": "directory.account",
            },
        },
        "inputs": [port("directory_action", "object"), port("target_account", "string")],
        "outputs": [port("directory_action", "object"), port("target_account", "string")],
    },
    {
        "id": "task.temporary_credential",
        "type": "simulation",
        "kind": "task",
        "label": "Step 4 \u00b7 Issue a temporary password, force a change at next sign-in (simulated)",
        "position": {"x": 2880, "y": 400},
        "data": {
            "menu": "Directory",
            "description": (
                "SIMULATED. Emits the fake temporary password, the force-change flag and the "
                "password policy the requester will have to satisfy. Deterministic on purpose: "
                "nothing on screen changes between two runs."
            ),
        },
        "config": {
            "runtime_ref": "builtin:passthrough",
            "inputs_map": {
                "temporary_password_issued": ref(
                    "system", "simulation", "temporary_password_issued"
                ),
                "force_change_at_next_logon": ref(
                    "system", "simulation", "force_change_at_next_logon"
                ),
                "password_policy": ref("system", "simulation", "password_policy"),
            },
            "outputs_map": {
                "temporary_password_issued": "directory.temporary_password_issued",
                "force_change_at_next_logon": "directory.force_change_at_next_logon",
            },
        },
        "inputs": [port("temporary_password_issued", "string")],
        "outputs": [
            port("temporary_password_issued", "string"),
            port("force_change_at_next_logon", "boolean"),
        ],
    },
    {
        "id": "task.draft_user_notice",
        "type": "llm",
        "kind": "task",
        "label": "Step 5 \u00b7 Draft the message to the requester (model call, EN/AR)",
        "position": {"x": 2880, "y": 580},
        "data": {
            "menu": "Generation",
            "description": (
                "REAL inference under a constrained template: English then Arabic, the temporary "
                "password, the change-at-first-sign-in instruction and the mandatory security "
                "warning, 90 words maximum per language."
            ),
        },
        "config": {
            "skill_slug": "azure_llm_v1",
            "skill_id": None,
            "inputs_map": {
                "prompt": ref("intake", "case", "notice_prompt"),
                "model": ref("system", "default_model"),
            },
            "outputs_map": {"completion": "notice.message"},
        },
        "inputs": [port("prompt", "string"), port("model", "string")],
        "outputs": [port("completion", "string"), port("model", "string")],
    },
    {
        "id": "task.close_ticket",
        "type": "simulation",
        "kind": "task",
        "label": "Step 6 \u00b7 Confirm the resolution and close the ticket (simulated)",
        "position": {"x": 2880, "y": 760},
        "data": {
            "menu": "Service desk",
            "description": "SIMULATED. Emits the closed ticket record and its resolution text.",
        },
        "config": {
            "runtime_ref": "builtin:passthrough",
            "inputs_map": {
                "ticket": ref("system", "simulation", "ticket"),
                "closed_by": ref("system", "simulation", "closed_by"),
            },
            "outputs_map": {"ticket": "closure.ticket"},
        },
        "inputs": [port("ticket", "object")],
        "outputs": [port("ticket", "object"), port("closed_by", "string")],
    },
    {
        "id": "task.audit_ledger",
        "type": "compliance",
        "kind": "task",
        "label": "Step 6 \u00b7 Write the audit ledger entry",
        "position": {"x": 2880, "y": 940},
        "data": {
            "menu": "Governance",
            "description": (
                "Real platform primitive (audit_log_v1). Records the privileged gesture, the "
                "account it applied to, the authorisation that allowed it and the approval "
                "Decision id when a human was involved."
            ),
        },
        "config": {
            "skill_slug": "audit_log_v1",
            "skill_id": None,
            "inputs_map": {
                "event_type": ref("system", "simulation", "audit_event_type"),
                "details": ref("system", "simulation", "audit_details"),
                "ticket_id": ref("system", "simulation", "ticket", "id"),
                "requester_account": ref("intake", "case", "requester_upn"),
                "authorisation": ref("decision.execute_reset", "chosen_branch"),
                "approval_decision_id": ref("hitl.identity_gate", "decision_id"),
            },
            "outputs_map": {"id": "closure.audit_event_id"},
        },
        "inputs": [port("event_type", "string"), port("details", "object")],
        "outputs": [port("id", "string"), port("status", "string")],
    },
    {
        "id": "decision.closure_route",
        "type": "decision",
        "kind": "decision",
        "label": "Step 6 \u00b7 Closure routing",
        "position": {"x": 3240, "y": 580},
        "data": {
            "menu": "Control",
            "description": (
                "Single convergence point for the whole procedure: the ticket is declared closed "
                "only when the closure record exists, and the refusal leaf opens only when a human "
                "actually said no. When the request never entered the reset procedure neither "
                "condition holds, both leaves are skipped and the run reports the routing outcome "
                "alone - a neutralised request can never surface as a resolved ticket."
            ),
        },
        "config": {
            "branches": [
                {"label": "closed", "condition": "ticket_state == 'closed'"},
                {"label": "refused", "condition": "human_approved == False"},
            ],
            "inputs_map": {
                "ticket_state": ref("closure", "ticket", "state"),
                "human_approved": ref("hitl.identity_gate", "approved"),
            },
        },
        "inputs": [port("ticket_state", "string"), port("human_approved", "boolean")],
        "outputs": [port("chosen_branch", "string")],
    },
    {
        "id": "task.audit_withheld_incident",
        "type": "compliance",
        "kind": "task",
        "label": "Step 6 \u00b7 Record the withheld reset in the audit ledger",
        "position": {"x": 2880, "y": 1060},
        "data": {
            "menu": "Governance",
            "description": (
                "The ledger records what was PREVENTED, not only what was done. A privileged "
                "write was authorised and not applied: the entry states that, with the reason and "
                "the timestamp, and asserts that the account was not modified. An empty ledger "
                "would prove nothing on this lane."
            ),
        },
        "config": {
            "skill_slug": "audit_log_v1",
            "skill_id": None,
            "inputs_map": {
                "event_type": ref(
                    "system", "simulation", "audit_withheld", "incident", "event_type"
                ),
                "details": ref("system", "simulation", "audit_withheld", "incident", "details"),
            },
            "outputs_map": {"id": "closure.withheld_audit_event_id"},
        },
        "inputs": [port("event_type", "string"), port("details", "object")],
        "outputs": [port("id", "string")],
    },
    {
        "id": "task.audit_withheld_quality",
        "type": "compliance",
        "kind": "task",
        "label": "Step 6 \u00b7 Record the held reset in the audit ledger",
        "position": {"x": 2880, "y": 1600},
        "data": {
            "menu": "Governance",
            "description": (
                "Same record on the governance lane: the reset was held before any change, the "
                "account was not modified, and the reason is the policy that was applied. This is "
                "the entry a compliance review asks for when it wants to know how often the "
                "platform refused rather than how often it succeeded."
            ),
        },
        "config": {
            "skill_slug": "audit_log_v1",
            "skill_id": None,
            "inputs_map": {
                "event_type": ref(
                    "system", "simulation", "audit_withheld", "quality_hold", "event_type"
                ),
                "details": ref(
                    "system", "simulation", "audit_withheld", "quality_hold", "details"
                ),
            },
            "outputs_map": {"id": "closure.withheld_audit_event_id"},
        },
        "inputs": [port("event_type", "string"), port("details", "object")],
        "outputs": [port("id", "string")],
    },
    {
        "id": "sink.incident",
        "type": "sink",
        "kind": "sink",
        "label": "Outcome \u00b7 Incident, automation bridge unreachable",
        "position": {"x": 2880, "y": 1240},
        "data": {
            "menu": "Outcome",
            "description": (
                "Terminal leaf for an infrastructure failure. The reset was authorised but could "
                "not be dispatched: nothing was written, nothing was half-applied. The leaf "
                "presents the BUSINESS incident - outcome.message says what happened to the "
                "request and to the account - and keeps the verbatim provider error under the "
                "diagnostic_ prefix, next to the same string in the trace. That split is the "
                "auditability argument itself: the operator reads the incident, the auditor reads "
                "the cause, and neither has to guess."
            ),
        },
        "config": {
            "inputs_map": {
                "outcome": ref("system", "outcomes", "incident"),
                "identity_verdict": ref("identity", "verdict"),
                "detected_intent": ref("intake", "intent"),
                # Everything below is for the execution journal, never for the
                # outcome card. Same prefix on every lane so the surface has a
                # single rule to apply.
                "diagnostic_job": ref("directory", "bridge_job"),
                "diagnostic_status": ref("directory", "bridge_status"),
                "diagnostic_detail": ref("directory", "bridge_error"),
            }
        },
        "inputs": [port("outcome", "object")],
        "outputs": [],
    },
    {
        "id": "sink.quality_hold",
        "type": "sink",
        "kind": "sink",
        "label": "Outcome \u00b7 Held for review, assessment not grounded",
        "position": {"x": 2880, "y": 1420},
        "data": {
            "menu": "Outcome",
            "description": (
                "Terminal leaf for a quality refusal. The model was confident and the grounding "
                "check disagreed: no evidence was on file, so the unattended privileged write is "
                "refused. Nothing here reads as a malfunction, because nothing malfunctioned - "
                "the leaf states a policy decision and the count that drove it. The evaluator "
                "scores stay under the diagnostic_ prefix: with an empty evidence record they are "
                "mechanically at their floor, which says something about the record and nothing "
                "about the model, and they must not be paraded as a defect rate."
            ),
        },
        "config": {
            "inputs_map": {
                "outcome": ref("system", "outcomes", "quality_hold"),
                "identity_verdict": ref("identity", "verdict"),
                "evidence_on_file": ref("quality", "evidence_count"),
                "detected_intent": ref("intake", "intent"),
                "diagnostic_quality_score": ref("quality", "score"),
                "diagnostic_hallucination_rate": ref("quality", "hallucination_rate"),
            }
        },
        "inputs": [port("outcome", "object")],
        "outputs": [],
    },
    {
        "id": "sink.approval_refused",
        "type": "sink",
        "kind": "sink",
        "label": "Outcome \u00b7 Human approval refused",
        "position": {"x": 3560, "y": 940},
        "data": {
            "menu": "Outcome",
            "description": (
                "Terminal leaf. The operator refused the gate: no directory write, no temporary "
                "password, no ticket closed. The refusal and its author stay in the ledger."
            ),
        },
        "config": {
            "inputs_map": {
                "outcome": ref("system", "outcomes", "refused"),
                "identity_verdict": ref("identity", "verdict"),
                "human_approval": ref("hitl.identity_gate"),
            }
        },
        "inputs": [port("outcome", "object")],
        "outputs": [],
    },
    {
        "id": "sink.ticket_closed",
        "type": "sink",
        "kind": "sink",
        "label": "Outcome \u00b7 Ticket closed",
        "position": {"x": 3560, "y": 580},
        "data": {
            "menu": "Outcome",
            "description": (
                "Terminal leaf reached only through the authorised execution block. Carries the "
                "closed ticket, the audit event id, the message sent to the requester and the "
                "human approval when there was one."
            ),
        },
        "config": {
            "inputs_map": {
                "outcome": ref("system", "outcomes", "closed"),
                "ticket": ref("closure", "ticket"),
                "audit_event_id": ref("closure", "audit_event_id"),
                "user_message": ref("notice", "message"),
                "directory_action": ref("directory", "reset"),
                "temporary_password_issued": ref(
                    "directory", "temporary_password_issued"
                ),
                "identity_verdict": ref("identity", "verdict"),
                "detected_intent": ref("intake", "intent"),
                "human_approval": ref("hitl.identity_gate"),
                # Grounding evidence for the closed ticket: how many filed
                # items backed the assessment, and what the evaluator scored.
                "evidence_on_file": ref("quality", "evidence_count"),
                "diagnostic_quality_score": ref("quality", "score"),
            }
        },
        "inputs": [port("outcome", "object"), port("ticket", "object")],
        "outputs": [],
    },
]

EDGES = [
    {"from": "source.request", "to": "decision.case_selector", "kind": "data"},
    {
        "from": "decision.case_selector",
        "to": "task.case_nominal",
        "kind": "branch",
        "branch_label": "nominal",
    },
    {
        "from": "decision.case_selector",
        "to": "task.case_ambiguous",
        "kind": "branch",
        "branch_label": "ambiguous",
    },
    {
        "from": "decision.case_selector",
        "to": "task.case_weak_identity",
        "kind": "branch",
        "branch_label": "weak_identity",
    },
    {
        "from": "decision.case_selector",
        "to": "task.case_ad_unreachable",
        "kind": "branch",
        "branch_label": "ad_unreachable",
    },
    # Same caller case, minus the bridge attempt: the remediation lane reuses
    # the case node and is the only branch that leaves task.directory_bridge out.
    {
        "from": "decision.case_selector",
        "to": "task.case_ad_unreachable",
        "kind": "branch",
        "branch_label": "ad_unreachable_bypass",
    },
    {
        "from": "decision.case_selector",
        "to": "task.directory_bridge",
        "kind": "branch",
        "branch_label": "ad_unreachable",
    },
    {
        "from": "decision.case_selector",
        "to": "task.case_quality_guard",
        "kind": "branch",
        "branch_label": "quality_guard",
    },
    {
        "from": "decision.case_selector",
        "to": "task.case_free_text",
        "kind": "branch",
        "branch_label": "free_text",
    },
    {"from": "task.case_nominal", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.case_ambiguous", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.case_weak_identity", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.case_ad_unreachable", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.case_quality_guard", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.case_free_text", "to": "task.classify_intent", "kind": "data"},
    {"from": "task.classify_intent", "to": "decision.intent_route", "kind": "data"},
    {
        "from": "decision.intent_route",
        "to": "sink.routed_elsewhere",
        "kind": "branch",
        "branch_label": "other_use_case",
    },
    {
        "from": "decision.intent_route",
        "to": "task.verify_identity",
        "kind": "branch",
        "branch_label": "password_reset",
    },
    {"from": "task.verify_identity", "to": "decision.identity_gate", "kind": "data"},
    {
        "from": "decision.identity_gate",
        "to": "hitl.identity_gate",
        "kind": "branch",
        "branch_label": "insufficient",
    },
    {
        "from": "decision.identity_gate",
        "to": "decision.execute_reset",
        "kind": "branch",
        "branch_label": "verified",
    },
    {
        "from": "decision.identity_gate",
        "to": "task.quality_gate",
        "kind": "branch",
        "branch_label": "verified",
    },
    {"from": "hitl.identity_gate", "to": "decision.execute_reset", "kind": "control"},
    # Ordering edges, not gating ones: they make decision.execute_reset wait for
    # the grounding check and the bridge attempt instead of racing them. Neither
    # can revive the authorisation point, which always runs.
    {"from": "task.quality_gate", "to": "decision.execute_reset", "kind": "data"},
    {"from": "task.directory_bridge", "to": "decision.execute_reset", "kind": "data"},
    {
        "from": "decision.execute_reset",
        "to": "sink.incident",
        "kind": "branch",
        "branch_label": "incident",
    },
    # Sibling of the sink, not its parent: a sink that is only killed by its
    # branch edge must keep that edge as its ONLY gating input, so the ledger
    # write runs alongside it rather than upstream of it.
    {
        "from": "decision.execute_reset",
        "to": "task.audit_withheld_incident",
        "kind": "branch",
        "branch_label": "incident",
    },
    {
        "from": "decision.execute_reset",
        "to": "sink.quality_hold",
        "kind": "branch",
        "branch_label": "quality_hold",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.audit_withheld_quality",
        "kind": "branch",
        "branch_label": "quality_hold",
    },
    {
        "from": "decision.execute_reset",
        "to": "decision.closure_route",
        "kind": "branch",
        "branch_label": "refused",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.ad_reset",
        "kind": "branch",
        "branch_label": "execute",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.temporary_credential",
        "kind": "branch",
        "branch_label": "execute",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.draft_user_notice",
        "kind": "branch",
        "branch_label": "execute",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.close_ticket",
        "kind": "branch",
        "branch_label": "execute",
    },
    {
        "from": "decision.execute_reset",
        "to": "task.audit_ledger",
        "kind": "branch",
        "branch_label": "execute",
    },
    {"from": "task.ad_reset", "to": "decision.closure_route", "kind": "data"},
    {"from": "task.temporary_credential", "to": "decision.closure_route", "kind": "data"},
    {"from": "task.draft_user_notice", "to": "decision.closure_route", "kind": "data"},
    {"from": "task.close_ticket", "to": "decision.closure_route", "kind": "data"},
    {"from": "task.audit_ledger", "to": "decision.closure_route", "kind": "data"},
    {
        "from": "decision.closure_route",
        "to": "sink.ticket_closed",
        "kind": "branch",
        "branch_label": "closed",
    },
    {
        "from": "decision.closure_route",
        "to": "sink.approval_refused",
        "kind": "branch",
        "branch_label": "refused",
    },
]

VARIABLE_NAMESPACES = ["intake", "identity", "directory", "notice", "closure", "quality"]

DATA_FLOW_NOTES = [
    "Walked by execute_run_dag(): schema_version 3 and real control nodes (decision + hitl). "
    "Without a control node the run would fall back to the sequential walker, which ignores the "
    "HITL gate entirely.",
    "The scenario input selects the INBOUND CASE only (which words the caller used, which identity "
    "evidence the agent collected). It never selects the outcome: step 1 and step 2 are real model "
    "calls and their output drives every downstream branch.",
    "decision nodes emit only {chosen_branch, evaluations}. Every downstream value is read from the "
    "variable pool through config.inputs_map (typed VariableRef), never from the branch payload.",
    "Branch pruning is transitive: a node skipped with all_inputs_dead marks every outgoing edge "
    "dead. The five execution steps remain explicit sibling lanes for audit readability, while a "
    "future multi-node tail is now neutralised safely as well.",
    "decision.identity_gate, decision.execute_reset and decision.closure_route deliberately have "
    "NO default_branch: when "
    "their input never materialised (the request was routed away at step 1) every branch closes and "
    "the whole procedure is neutralised. decision.intent_route, by contrast, defaults to "
    "other_use_case so an unreadable classification can never trigger a privileged write.",
    "decision.closure_route remains the explicit business completion gate: it joins the five "
    "steps plus the refusal branch and "
    "opens 'closed' only when the closure record exists, 'refused' only when a human said no. "
    "Without it sink.ticket_closed would fire on a neutralised lane and report a resolved ticket.",
    "sink.ticket_closed reads its whole payload from the pool through inputs_map, so the outcome "
    "leaf that fires is the only one contributing to Run.output_ref.",
    "The simulated gestures (steps 3, 4, 6) are explicitly bound to builtin:passthrough: they "
    "resolve inputs_map against system.simulation.* and emit it as their output. Editing the fake temporary "
    "password, ticket id or resolution text is a System settings change, not a flow change.",
    "decision.execute_reset checks its four branches IN ORDER: incident, quality_hold, execute, "
    "refused. Every condition is written so that a missing input reads as False (None == 0 and "
    "None == 'failed' are both false), which is why the lanes that never populate the bridge "
    "status or the evidence count are unaffected by the two guards.",
    "task.directory_bridge is the ONLY node that reaches outside the platform, and it hangs "
    "directly off decision.case_selector so that every other lane skips it with all_inputs_dead - "
    "no other scenario can pay for a connector call. The ad_unreachable_bypass branch loads the "
    "same caller case without it: that is the remediation run, and it succeeds.",
    "task.quality_gate hangs off the 'verified' branch of decision.identity_gate, so it guards the "
    "unattended lane only. On the human-gate lane the operator is the control, and on a routed-out "
    "lane there is nothing to guard. Its edge into decision.execute_reset carries no branch label: "
    "it exists to order the two nodes, not to gate the authorisation point.",
    "The ledger is written on three lanes, not one: the completed reset, and the two lanes where "
    "a privileged write was authorised and withheld. The withheld entries state the disposition, "
    "the reason and that the account was not modified, because an auditor needs to prove what was "
    "PREVENTED and a silent lane proves nothing. Each is a SIBLING of its outcome leaf, never its "
    "parent: a leaf whose only gating input is its branch edge would come back to life on every "
    "other lane the moment a second, non-branch edge fed it.",
    "Every outcome carries code + label + message, and the message is written for a human who "
    "does not know what a connector is: it says what happened to the REQUEST and to the ACCOUNT. "
    "Anything that names a component, a provider or an error string lives under a diagnostic_ key "
    "of the sink payload, and the verbatim provider error also stays in the trace on the failing "
    "node. One rule for the surface: present outcome.*, relegate diagnostic_*.",
    "Only context_count gates the quality branch. The platform evaluator computes it from the "
    "payload rather than from the embedding backend, so the guard cannot be flipped by an "
    "infrastructure degradation: a degraded evaluator returns zeroed scores, which are reported "
    "on the outcome but never block a run.",
]

FALLBACK_NOTES = [
    "Same node ids, same edges, same labels as the LLM flow. The twin binds NO skill except "
    "audit_log_v1: the three model calls, the connector dispatch and the evaluator all become "
    "no-skill pass-throughs reading a canned value (simulated_intent, simulated_identity_verdict, "
    "simulated_user_message, simulated_evidence_count, and the canned bridge failure record). "
    "Every branch condition is untouched, so the five scenarios behave exactly the same way, HITL "
    "gate included, with zero calls leaving the platform.",
    "One observable difference: the incident lane shows a COMPLETED node carrying a failed status "
    "instead of a failed invocation, because the twin never dispatches to the bridge. The outcome, "
    "the skipped execution steps and the remediation path are identical.",
    "Switch: PATCH /api/v1/systems/{id} with flow_definition = this object (available on the same "
    "System under settings.fallback_flow_definition). Switch back with settings.primary_flow_ref.",
]


def flow_definition(nodes, *, variant: str, notes) -> dict:
    return {
        "schema_version": 3,
        "variant": variant,
        "source": "scaffold_artifact",
        "template_id": "nawa-password-reset-v1",
        "template_name": "Password Reset (NAWA WE)",
        "variable_namespaces": list(VARIABLE_NAMESPACES),
        "data_flow_notes": list(notes),
        "nodes": copy.deepcopy(nodes),
        "edges": copy.deepcopy(EDGES),
        "ui": {
            "type": "itsd_password_reset",
            "label": "Password Reset",
            "entry_route": "systems",
            "flow_builder_enabled": True,
        },
        "policy": {
            "enable_audit": True,
            "max_latency_ms": 45000,
            "simulated_system_actions": True,
            "real_directory_integration": False,
        },
    }


# --- fully simulated twin --------------------------------------------------
_CANNED = {
    "task.classify_intent": "simulated_intent",
    "task.verify_identity": "simulated_identity_verdict",
    "task.draft_user_notice": "simulated_user_message",
}


# Nodes whose canned replacement is not a plain `completion` string. The twin
# binds NO skill at all, so the two connector/evaluator nodes read a canned
# payload the same way the simulated directory gestures do.
_CANNED_STRUCTURED = {
    "task.directory_bridge": {
        "label_from": "Dispatch the reset to the automation bridge",
        "label_to": "Automation bridge dispatch (canned failure)",
        "description": (
            "FALLBACK VARIANT - no connector call. Emits the canned failure record stored on the "
            "System settings, so the incident lane behaves exactly as it does with the real "
            "bridge. The trace shows a completed node carrying a failed status rather than a "
            "failed invocation: that is the one observable difference between the two variants."
        ),
        "inputs_map": {
            "_status": ref("system", "simulation", "directory_bridge_failure", "_status"),
            "_error": ref("system", "simulation", "directory_bridge_failure", "_error"),
            "job_key": ref("system", "simulation", "directory_bridge", "job_key"),
        },
        "inputs": [port("_status", "string")],
        "outputs": [port("_status", "string")],
    },
    "task.quality_gate": {
        "label_from": "Grounding check on the identity assessment",
        "label_to": "Grounding check on the identity assessment (canned)",
        "description": (
            "FALLBACK VARIANT - no evaluator call. Replays the number of evidence items filed on "
            "the scenario preset, which is the only value the authorisation point reads, so the "
            "guard opens and closes on exactly the same lanes as with the real evaluator."
        ),
        "inputs_map": {
            "context_count": ref("intake", "case", "simulated_evidence_count"),
        },
        "inputs": [port("context_count", "number")],
        "outputs": [port("context_count", "number")],
    },
}


def simulated_nodes(nodes):
    out = []
    for node in copy.deepcopy(nodes):
        structured = _CANNED_STRUCTURED.get(node["id"])
        if structured is not None:
            node["type"] = "simulation"
            node["label"] = node["label"].replace(
                structured["label_from"], structured["label_to"]
            )
            node["data"]["description"] = structured["description"]
            node["config"] = {
                "inputs_map": dict(structured["inputs_map"]),
                "outputs_map": dict(node["config"]["outputs_map"]),
            }
            node["inputs"] = list(structured["inputs"])
            node["outputs"] = list(structured["outputs"])
            out.append(node)
            continue
        preset_key = _CANNED.get(node["id"])
        if preset_key is None:
            out.append(node)
            continue
        node["type"] = "simulation"
        node["label"] = node["label"].replace("(model call, EN/AR)", "(canned, EN/AR)")
        node["label"] = node["label"].replace("(model call)", "(canned)")
        node["data"]["description"] = (
            "FALLBACK VARIANT - no provider call. Replays the canned model output stored on the "
            "scenario preset ("
            + preset_key
            + "), so the branch conditions downstream see exactly the same shape as the real "
            "inference."
        )
        node["config"] = {
            "inputs_map": {"completion": ref("intake", "case", preset_key)},
            "outputs_map": dict(node["config"]["outputs_map"]),
        }
        node["inputs"] = [port("completion", "string")]
        node["outputs"] = [port("completion", "string")]
        out.append(node)
    return out


ARTIFACT = {
    "artifact": "nawa_password_reset_v1",
    "description": (
        "Nawa ITSD demo (2026-07-29) - System 'Password Reset' for the nawa workspace, seeded by "
        "migration 065_nawa_itsd. Models the SIX-STEP MANUAL service desk procedure taken over by "
        "an agent: intake, identity verification, directory reset, temporary password, message to "
        "the requester, closure. Two real inference points (intent classification constrained to a "
        "closed enum, identity assessment with explicit abstention) plus one durable human gate; "
        "every system gesture is SIMULATED in dry-run semantics - no directory is ever contacted. "
        "The run input 'scenario' selects which inbound case is injected on the simulation bench "
        "(nominal | ambiguous | weak_identity | ad_unreachable | quality_guard); it never selects "
        "the outcome. 'free_text' takes the case from the run input instead, for a request typed "
        "in the business app, and is judged by the same instruction blocks. Also carries "
        "fallback_flow_definition: the same graph with the three model calls replaced by canned "
        "outputs, for a sub-minute switch if the provider degrades during the demo. Assistant name "
        "is NAWA WE (Workspace Engine)."
    ),
    "system": {
        "name": "Password Reset",
        "objective": (
            "Take over the Nawa IT service desk password-reset procedure end to end: classify the "
            "inbound request, assess the identity evidence against policy and abstain when it is "
            "insufficient, escalate to a human gate before any privileged action, then perform the "
            "reset, issue a temporary password, notify the requester in English and Arabic and "
            "close the ticket with an audit ledger entry. All directory gestures are simulated."
        ),
        "capability_slug": "workspace_assistant",
        "execution_mode": "human_augmented",
        "coordination_pattern": "single_agent",
        "default_model": "gpt-4o-mini",
        "note": (
            "Walked by execute_run_dag() because the flow carries control nodes (decision + hitl). "
            "The hitl kind is not in the Flow Builder palette at this release, so the flow is "
            "authored as this artifact rather than by drag and drop - the builder still renders it "
            "and can resolve the pending gate."
        ),
    },
    "system_settings": {
        "system_type": "itsd_password_reset",
        "surface": "nawa-itsd",
        "surface_routes": ["/nawa/itsd", "/nawa/itsd/password-reset"],
        "assistant_name": ASSISTANT,
        "assistant_subtitle": "Workspace Engine",
        "use_case": {"code": "UC-01", "title": "Password Reset", "status": "live"},
        "scenarios": [
            "nominal",
            "ambiguous",
            "weak_identity",
            "ad_unreachable",
            "quality_guard",
            "free_text",
        ],
        "scenario_presets": SCENARIO_PRESETS,
        "free_text": FREE_TEXT,
        "simulation": SIMULATION,
        "outcomes": OUTCOMES,
        "quality_gate": {"question": QUALITY_QUESTION},
        "primary_flow_ref": "nawa_password_reset_v1.flow_definition",
    },
    "flow_definition": flow_definition(
        NODES, variant="itsd_password_reset_v1", notes=DATA_FLOW_NOTES
    ),
    "fallback_flow_definition": flow_definition(
        simulated_nodes(NODES),
        variant="itsd_password_reset_simulated_v1",
        notes=DATA_FLOW_NOTES + FALLBACK_NOTES,
    ),
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(ARTIFACT, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
print(
    "nodes:",
    len(ARTIFACT["flow_definition"]["nodes"]),
    "edges:",
    len(ARTIFACT["flow_definition"]["edges"]),
)
