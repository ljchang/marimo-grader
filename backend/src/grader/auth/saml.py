"""Dartmouth SAML 2.0 service provider.

Settings mirror the working configuration from pbs_knowledge's
``samlAuthService.ts``: Dartmouth signs the assertion (not the response),
allows ~2 minutes of clock skew, needs RequestedAuthnContext disabled for
Shibboleth, and the SP signs its AuthnRequests. The NetID is read from
eduPersonPrincipalName, not from the NameID.

python3-saml is imported lazily so the dev auth mode works without xmlsec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request

from grader.config import Settings, get_settings

OID = {
    "eppn": "urn:oid:1.3.6.1.4.1.5923.1.1.1.6",
    "uid": "urn:oid:0.9.2342.19200300.100.1.1",
    "mail": "urn:oid:0.9.2342.19200300.100.1.3",
    "givenName": "urn:oid:2.5.4.42",
    "sn": "urn:oid:2.5.4.4",
    "displayName": "urn:oid:2.16.840.1.113730.3.1.241",
    "affiliation": "urn:oid:1.3.6.1.4.1.5923.1.1.1.1",
}


@dataclass
class SamlIdentity:
    netid: str
    display_name: str | None
    affiliations: list[str]
    name_id: str | None
    session_index: str | None


def _strip_pem(cert: str) -> str:
    return "".join(line.strip() for line in cert.strip().splitlines() if "-----" not in line)


def build_settings(s: Settings) -> dict[str, Any]:
    base = f"{s.base_url}/api/v1/auth/saml"
    return {
        "strict": True,
        "debug": s.env != "prod",
        "sp": {
            "entityId": s.saml_sp_entity_id or s.base_url,
            "assertionConsumerService": {
                "url": f"{base}/acs",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
            "x509cert": _strip_pem(s.saml_sp_cert or ""),
            "privateKey": _strip_pem(s.saml_sp_key or ""),
        },
        "idp": {
            "entityId": s.saml_idp_entity_id,
            "singleSignOnService": {
                "url": s.saml_idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "singleLogoutService": {
                "url": s.saml_idp_logout_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": _strip_pem(s.saml_idp_cert or ""),
        },
        "security": {
            "authnRequestsSigned": True,
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameId": False,
            "requestedAuthnContext": False,
            "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
            "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
            "allowRepeatAttributeName": True,
        },
        "contactPerson": {
            "technical": {
                "givenName": "DartBrains Grader",
                "emailAddress": "luke.j.chang@dartmouth.edu",
            }
        },
        "organization": {
            "en-US": {
                "name": "DartBrains",
                "displayname": "DartBrains Grader",
                "url": "https://dartbrains.org",
            }
        },
    }


async def _request_data(request: Request) -> dict[str, Any]:
    form = await request.form() if request.method == "POST" else {}
    s = get_settings()
    https = "on" if s.base_url.startswith("https") else "off"
    host = s.base_url.split("://", 1)[1].split("/", 1)[0]
    return {
        "https": https,
        "http_host": host,
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": {k: v for k, v in form.items() if isinstance(v, str)},
    }


def _auth(req_data: dict[str, Any]):
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # lazy: needs xmlsec

    return OneLogin_Saml2_Auth(req_data, build_settings(get_settings()))


async def login_url(request: Request, relay_state: str) -> str:
    auth = _auth(await _request_data(request))
    return auth.login(return_to=relay_state)


async def process_response(request: Request) -> SamlIdentity:
    auth = _auth(await _request_data(request))
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        raise ValueError(f"SAML error: {', '.join(errors)} ({auth.get_last_error_reason()})")
    if not auth.is_authenticated():
        raise ValueError("SAML: not authenticated")
    attrs = auth.get_attributes()

    def first(*names: str) -> str | None:
        for n in names:
            v = attrs.get(n)
            if v:
                return v[0] if isinstance(v, list) else v
        return None

    eppn = first("eduPersonPrincipalName", OID["eppn"])
    netid = eppn.split("@", 1)[0] if eppn else first("uid", OID["uid"]) or auth.get_nameid() or ""
    netid = netid.strip().lower()
    if not netid:
        raise ValueError("SAML: no NetID in assertion")
    given = first("givenName", OID["givenName"])
    sn = first("sn", OID["sn"])
    display = (
        first("displayName", OID["displayName"]) or " ".join(x for x in (given, sn) if x) or None
    )
    aff = attrs.get("eduPersonAffiliation") or attrs.get(OID["affiliation"]) or []
    return SamlIdentity(
        netid=netid,
        display_name=display,
        affiliations=[a.lower() for a in (aff if isinstance(aff, list) else [aff])],
        name_id=auth.get_nameid(),
        session_index=auth.get_session_index(),
    )


def metadata_xml() -> str:
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    st = OneLogin_Saml2_Settings(build_settings(get_settings()), sp_validation_only=True)
    xml = st.get_sp_metadata()
    errors = st.validate_metadata(xml)
    if errors:
        raise ValueError("invalid SP metadata: " + ", ".join(errors))
    return xml.decode() if isinstance(xml, bytes) else xml
