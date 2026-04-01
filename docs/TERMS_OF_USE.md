# Terms of Use

**Project:** ONTO — Ontological Context System
**Version:** Draft 1.1
**Status:** Pending legal review (checklist item 4.01)
**Last updated:** 2026-04-01

> **Notice:** This is a working draft. It has not been reviewed by legal
> counsel. It must not be used as final terms of use for any deployment
> without professional legal review. See checklist item 4.01.

---

## Plain language summary

- ONTO is free, open source, and provided as-is.
- You are responsible for how you use it.
- You may not use it to harm people.
- The principles are non-negotiable — the system will not help you
  violate them.
- If you deploy it for others, you take on responsibility for that deployment.
- No warranties. No guarantees. Use good judgment.

---

## 1. What ONTO is

ONTO is an open-source software system licensed under the GNU Lesser
General Public License v2.1 (LGPL-2.1). It is provided as a tool to
help people make sense of information in context.

It is not a medical device, a legal advisor, a financial advisor,
a mental health service, or a crisis intervention service. It is
software. The humans using it are responsible for the decisions they make.

---

## 2. Who may use ONTO

Anyone may use ONTO, subject to these terms.

You must not use ONTO if you are prohibited from doing so by applicable
law in your jurisdiction.

---

## 3. What you may do

You may:
- Use ONTO for any personal, educational, research, or commercial purpose
- Modify ONTO under the terms of the LGPL-2.1 License
  (modifications to the library itself must be shared back under
  the same license)
- Distribute ONTO under the terms of the LGPL-2.1 License
- Deploy ONTO for others to use (subject to Section 7)
- Build proprietary applications that use ONTO without modifying it

The LGPL-2.1 License governs all use, modification, and distribution
of the software itself. See the LICENSE and NOTICE files for full terms.

---

## 4. What you may not do

You must not use ONTO to:
- Harm, threaten, harass, or stalk any person
- Collect or process personal data without the informed consent of
  the person whose data it is
- Circumvent, disable, or remove the human sovereignty checkpoint
- Circumvent, disable, or remove the audit trail
- Circumvent, disable, or remove the crisis detection and response layer
- Deceive users about what the system is recording or doing
- Violate any applicable law or regulation
- Infringe the rights of any third party

Attempts to override the system's principles are recorded in the
permanent audit trail.

---

## 5. The principles are non-negotiable

The 13 principles sealed in `principles.txt` govern the system's
behavior. They cannot be overridden by user input, operator configuration,
or code modification without breaking the integrity verification.

By using ONTO, you agree to operate within these principles. You do
not have to agree with them — but the system will not help you
violate them.

The principles are:
1. Purpose — to help, not to control
2. Life First — human wellbeing above all else
3. Freedom — every person's right to choose
4. Truth — honest, calibrated outputs only
5. Do No Harm — active avoidance of harm
6. Openness — transparent about what it sees and how it works
7. Memory — permanent, honest record of everything
8. Integrity — the system keeps its promises
9. Humility — uncertainty is a first-class output
10. Growth — learning without manipulation
11. Dignity — every person deserves respect
12. Consent — nothing without agreement
13. Accountability — everything is recorded

Read the full text in `principles.txt`.

---

## 6. Crisis detection and safety

ONTO monitors all inputs for signals that may indicate someone is in
distress. This is a safety feature and cannot be disabled.

ONTO is not a crisis service. If you or someone you know is in crisis:
- Call or text 988 (US Suicide & Crisis Lifeline)
- Text HOME to 741741 (Crisis Text Line)
- Visit findahelpline.com for international resources
- Call emergency services if there is immediate danger

The crisis detection in ONTO is pattern-based and not comprehensive.
It is a supplement to — not a replacement for — human judgment and
professional crisis services.

---

## 7. Operator responsibilities

If you deploy ONTO for others to use, you are an operator. You agree to:

- Provide users with a clear privacy policy before they use the system
- Obtain appropriate consent from users for data collection
- Comply with all applicable data protection and privacy laws
- Secure the deployment appropriately for the sensitivity of data processed
- Not remove or weaken any safety features
- Not misrepresent what the system is or what it records
- Take responsibility for how your deployment is used

Operators in the EU must comply with GDPR. Operators in California
must comply with CCPA. Operators in healthcare, legal, financial,
or other regulated contexts must comply with applicable sectoral
regulations. Legal counsel is strongly recommended.

---

## 8. High-risk deployments

ONTO may qualify as a high-risk AI system under the EU AI Act if
deployed in healthcare, legal proceedings, employment decisions,
education, or financial services contexts.

If your deployment falls into a high-risk category, you must:
- Conduct a conformity assessment before deployment
- Maintain technical documentation as required by Article 11
- Ensure human oversight as required by Article 14
- Log events for a minimum of 6 months as required by Article 26

ONTO's audit trail and human sovereignty checkpoint are designed to
support these requirements. Whether they fully satisfy them in your
specific deployment depends on context that this document cannot assess.
Legal counsel with EU AI Act expertise is required.

---

## 9. No warranties

ONTO is provided "as is," without warranty of any kind, express or
implied, including but not limited to:

- Fitness for a particular purpose
- Accuracy of outputs
- Completeness of context
- Reliability of crisis detection
- Suitability for regulated industries or high-risk applications

The system's outputs are presented with explicit confidence levels and
uncertainty markers by design. They are examined context — not
conclusions, advice, or guarantees.

The humans using the system are responsible for the decisions they make.

---

## 10. Limitation of liability

To the maximum extent permitted by applicable law, the contributors
to ONTO shall not be liable for any direct, indirect, incidental,
special, consequential, or punitive damages arising from the use
or inability to use the software.

This limitation applies regardless of the legal theory on which
any claim is based.

---

## 11. License

The software is licensed under the GNU Lesser General Public License
v2.1 (LGPL-2.1). The full text of the license is in the `LICENSE`
file in the repository. The `NOTICE` file contains the copyright
assertion and intellectual property notices.

LGPL-2.1 means: you may use ONTO freely, including in proprietary
applications built on top of it. If you modify ONTO's source code
itself, those modifications must be released under LGPL-2.1.

The LGPL-2.1 governs the software. These Terms of Use govern
responsible use of the software. Both apply.

Patent applications may be pending. See the `NOTICE` file.

---

## 12. Changes to these terms

These terms will be updated as the project evolves. Changes will be
documented in `CHANGELOG.md`. The version and date at the top of
this document reflect the current state.

Continued use of ONTO after changes to these terms constitutes
acceptance of the updated terms.

---

## 13. Governing law

These terms are currently ungoverned — there is no legal entity,
no jurisdiction, and no formal dispute resolution mechanism. This
will change as the project matures and legal foundations are
established (checklist item 4.01).

Until then, disputes should be raised as GitHub issues and resolved
through the governance process described in `GOVERNANCE.md`.

---

## 14. Legal status of this document

This document is a draft produced for an open-source project with
no legal entity, no employed staff, and no revenue.

It has not been reviewed by legal counsel. Before deploying ONTO in
any production context, especially one involving regulated industries,
vulnerable populations, or significant personal data, consult a
qualified lawyer.

---

*These terms are part of the permanent record of ONTO.*
*They are updated as the project and its legal understanding evolves.*
*They are honest about what is not yet settled.*
