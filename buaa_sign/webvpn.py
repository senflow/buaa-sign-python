"""Restricted BUAA WebVPN address mapping; no credentials or general proxy.

These fixed host tokens are the gateway's AES-CFB URL representation, not
secrets. Keeping an allowlist avoids a runtime crypto dependency and prevents
authentication redirects from selecting arbitrary upstream hosts or ports.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

GATEWAY = "https://d.buaa.edu.cn"
TOKENS = {
    "d.buaa.edu.cn": "77726476706e69737468656265737421f4b94389263126557a1dc7af96",
    "sso.buaa.edu.cn": "77726476706e69737468656265737421e3e44ed225256951300d8db9d6562d",
    "iclass.buaa.edu.cn": "77726476706e69737468656265737421f9f44d9d342326526b0988e29d51367ba018",
    "uc.buaa.edu.cn": "77726476706e69737468656265737421e5f40f9e3231691e7b0c9ce29b5b",
}
ORIGINS = {
    ("sso.buaa.edu.cn", "https", 443),
    ("uc.buaa.edu.cn", "https", 443),
    ("iclass.buaa.edu.cn", "https", 8346),
    ("iclass.buaa.edu.cn", "https", 8347),
    ("iclass.buaa.edu.cn", "http", 8081),
}
PORTAL_PATHS = ("/", "/login", "/logout", "/wengine-vpn-token-login", "/token-login")


def _prefix(host, scheme, port):
    protocol = scheme if port == {"http": 80, "https": 443}[scheme] else f"{scheme}-{port}"
    return f"/{protocol}/{TOKENS[host]}"


def original_url(url):
    """Validate a direct/gateway URL and recover its logical origin."""
    if any(c in url for c in ("\\", "\r", "\n", "\t")):
        raise ValueError("不支持的 WebVPN 地址")
    p = urlsplit(url)
    if p.username is not None or p.password is not None or p.scheme not in ("https", "http"):
        raise ValueError("不支持的 WebVPN 地址")
    port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)
    if p.hostname == "d.buaa.edu.cn":
        if p.scheme != "https" or port != 443:
            raise ValueError("WebVPN 必须使用 HTTPS")
        # CAS rewrites its portal callback as an encoded upstream URL too.
        # Unwrap only this exact HTTPS origin, retaining the portal route list.
        portal_prefix = _prefix("d.buaa.edu.cn", "https", 443)
        if p.path == portal_prefix or p.path.startswith(portal_prefix + "/"):
            path = p.path[len(portal_prefix):] or "/"
            if path not in PORTAL_PATHS:
                raise ValueError("不支持的 WebVPN 门户路径")
            return urlunsplit(("https", "d.buaa.edu.cn", path, p.query, p.fragment))
        for host, scheme, target_port in ORIGINS:
            prefix = _prefix(host, scheme, target_port)
            if p.path == prefix or p.path.startswith(prefix + "/"):
                path = p.path[len(prefix):] or "/"
                return urlunsplit((scheme, f"{host}:{target_port}", path, p.query, p.fragment))
        # Only known portal routes may be visited without an upstream mapping.
        if (p.path or "/") in PORTAL_PATHS:
            return urlunsplit(("https", "d.buaa.edu.cn", p.path or "/", p.query, p.fragment))
        raise ValueError("WebVPN 跳转目标不在支持的学校服务范围内")
    if (p.hostname, p.scheme, port) not in ORIGINS:
        raise ValueError("WebVPN 跳转目标不在支持的学校服务范围内")
    return url


def gateway_url(url):
    original_url(url)
    p = urlsplit(url)
    if p.hostname == "d.buaa.edu.cn":
        return url
    port = p.port if p.port is not None else (443 if p.scheme == "https" else 80)
    return GATEWAY + _prefix(p.hostname, p.scheme, port) + urlunsplit(("", "", p.path or "/", p.query, p.fragment))


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form":
            self.current = {"action": fields.get("action", ""), "fields": {}, "password": False, "captcha": False}
            self.forms.append(self.current)
        if tag != "input" or self.current is None:
            return
        name, kind = fields.get("name", ""), fields.get("type", "text").lower()
        if kind == "password":
            self.current["password"] = True
        if kind != "hidden" and any(s in name.lower() for s in ("captcha", "validatecode", "verificationcode")):
            self.current["captcha"] = True
        if not name or kind in ("submit", "button", "image", "file"):
            return
        if kind in ("checkbox", "radio") and "checked" not in fields:
            return
        self.current["fields"][name] = fields.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None

    @property
    def login(self):
        return next((f for f in self.forms if f["password"] and "execution" in f["fields"]), None)
