# SAML service provider registration with Dartmouth IT

Send this once the staging host is up and serving `/api/v1/auth/saml/metadata`. It follows the
request that worked for dartmouthpbs.org (`pbs_knowledge/docs/security/EMAIL_TO_DARTMOUTH_IT.md`).
Replace the hostname if the staging host differs from `grader.dartbrains.org`.

Before sending, set on the server: `GRADER_SAML_SP_ENTITY_ID`, `GRADER_SAML_SP_CERT`,
`GRADER_SAML_SP_KEY` (self-signed, 10-year; `openssl req -x509 -newkey rsa:2048 -nodes -days 3650
-subj "/CN=grader.dartbrains.org" -keyout sp-key.pem -out sp-cert.pem`) and
`GRADER_SAML_IDP_CERT` (from `pbs_knowledge/backend/dartmouth-idp-metadata.xml`). Keep
`GRADER_AUTH_MODE=disabled` until IT confirms; the metadata endpoint works in either mode.

---

**To:** Dartmouth IT Support / WebAuth team
**Subject:** SAML Service Provider registration – DartBrains course grader

Hi,

I'm requesting registration of a new SAML service provider for a course tool used by
Psychological and Brain Sciences: the DartBrains grader, which lets students in PSYC 60
(Introduction to Neuroimaging) submit computational assignments from a notebook and lets the
teaching staff grade them. The application is the same architecture as the PBS Knowledge
application you registered for dartmouthpbs.org.

**Entity ID:** `https://grader.dartbrains.org`
**Assertion Consumer Service (HTTP-POST):** `https://grader.dartbrains.org/api/v1/auth/saml/acs`
**Metadata URL:** `https://grader.dartbrains.org/api/v1/auth/saml/metadata`

**Attributes requested** (as released to dartmouthpbs.org):
`eduPersonPrincipalName` (we derive the NetID from it), `displayName`, `givenName`, `sn`,
`eduPersonAffiliation`.

**Authorization:** all current Dartmouth students, faculty, and staff. Enrollment in a course is
managed inside the application from the Canvas roster; SSO only establishes identity.

**Technical details:** AuthnRequests signed; assertions signed (response envelope unsigned is
fine); SHA-256; NameID format unspecified; Duo handled by the IdP.

**Data handled:** NetID, display name, assignment submissions, and grades for enrolled students.
Hosted on a DigitalOcean droplet with a managed, encrypted PostgreSQL database during the
current pilot; I have shared the design document with ITS for review and will move the
service to Dartmouth-managed infrastructure if that is preferred.

Technical contact: Luke Chang, luke.j.chang@dartmouth.edu, Psychological and Brain Sciences.

Thank you,
Luke
