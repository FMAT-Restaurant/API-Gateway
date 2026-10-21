"""Regression tests: execute Lua with a mocked Kong PDK; Docker checks are separate."""
import json
from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime
import yaml

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "urn:fmat:restaurant:auth"


class GatewayTests(unittest.TestCase):
    def lua(self):
        return LuaRuntime(unpack_returned_tuples=True)

    def render(self, secret="a" * 32, origins="http://localhost:5173"):
        lua = self.lua()
        lua.globals().test_secret = secret
        lua.globals().test_origins = origins
        lua.globals().test_template = (ROOT / "config/kong.yml").read_text(encoding="utf-8")

        def encode(value):
            if lua.eval("type")(value) == "table":
                value = list(value.values())
            return json.dumps(value)

        lua.globals().test_encode = encode
        lua.execute('''
          package.preload["cjson.safe"] = function() return { encode = test_encode } end
          os.getenv = function(key)
            if key == "JWT_SECRET" then return test_secret end
            if key == "CORS_ORIGINS" then return test_origins end
          end
          io.open = function(path, mode)
            if mode == "r" then
              assert(path == "/usr/local/kong/declarative/kong.yml.template")
              return { read = function() return test_template end, close = function() end }
            end
            assert(path == "/tmp/kong.yml")
            return {
              write = function(_, value) test_output = value; return true end,
              close = function() return true end,
            }
          end
        ''')
        lua.execute((ROOT / "config/render.lua").read_text(encoding="utf-8"))
        return yaml.safe_load(lua.globals().test_output)

    def access(self, claims=None, path="/api/v1/menu", method="GET", token="signed.jwt.token",
               credential=True, required=True, parser_failure=False):
        lua = self.lua()
        if claims is None:
            claims = {"iss": ISSUER, "sub": "user-1"}
        lua.globals().claims = lua.table_from(claims, recursive=True)
        lua.globals().request_path = path
        lua.globals().request_method = method
        lua.globals().token = token
        lua.globals().credential = credential
        lua.globals().parser_failure = parser_failure
        lua.execute('''
          package.preload["kong.plugins.jwt.jwt_parser"] = function()
            return { new = function(_, value)
              assert(value == "signed.jwt.token")
              if parser_failure then return nil, "bad token" end
              return { claims = claims }
            end }
          end
          headers = {
            ["X-User-Id"] = "spoof", ["X-Staff-Id"] = "spoof",
            ["X-User-Roles"] = "admin", ["X-User-Permissions"] = "all"
          }
          kong = {
            ctx = { shared = { authenticated_jwt_token = token } },
            client = { get_credential = function() return credential end },
            request = {
              get_path = function() return request_path end,
              get_method = function() return request_method end,
            },
            service = { request = {
              clear_header = function(key) headers[key] = nil end,
              set_header = function(key, value) headers[key] = value end,
            } },
            response = { exit = function(status, body)
              response_status = status; response_body = body; return status
            end },
          }
        ''')
        handler = lua.execute((ROOT / "plugins/auth-perimeter/handler.lua").read_text(encoding="utf-8"))
        handler.access(handler, lua.table_from({"require_jwt": required, "issuer": ISSUER}))
        return lua.globals().response_status, dict(lua.globals().headers.items()), lua.globals().response_body

    def test_verified_string_is_decoded_and_identity_replaces_spoofed_headers(self):
        status, headers, _ = self.access({"iss": ISSUER, "sub": "123", "staffId": 42,
                                          "roles": ["waiter"], "permissions": ["orders:read", "orders:create"]})
        self.assertIsNone(status)
        self.assertEqual(headers, {"X-User-Id": "123", "X-Staff-Id": "42",
                                   "X-User-Roles": "waiter", "X-User-Permissions": "orders:read,orders:create"})

    def test_public_requests_clear_identity_without_requiring_token(self):
        status, headers, _ = self.access(token=None, credential=False, required=False)
        self.assertIsNone(status)
        self.assertEqual(headers, {})

    def test_protected_requests_fail_closed(self):
        for args in ({"token": None}, {"credential": False}, {"parser_failure": True}):
            with self.subTest(args=args):
                self.assertEqual(self.access(**args)[0], 401)

    def test_password_change_restrictions_and_exceptions(self):
        claims = {"iss": ISSUER, "sub": "123", "mustChangePassword": True}
        self.assertEqual(self.access(claims)[0], 403)
        self.assertEqual(self.access(claims)[2]["code"], "PASSWORD_CHANGE_REQUIRED")
        for path, method in (("me", "GET"), ("logout", "POST"), ("change-initial-password", "POST")):
            for suffix in ("", "/"):
                self.assertIsNone(self.access(claims, f"/api/v1/auth/{path}{suffix}", method)[0])
        self.assertEqual(self.access(claims, "/api/v1/auth/me", "POST")[0], 403)

    def test_invalid_claims_return_401_without_header_injection_or_crash(self):
        for patch in ({"iss": "wrong"}, {"sub": ""}, {"sub": "a\r\nb"},
                      {"staffId": {}}, {"mustChangePassword": "true"},
                      {"roles": [True]}, {"roles": ["admin,root"]},
                      {"permissions": {"key": "all"}}, {"permissions": "all"}):
            with self.subTest(patch=patch):
                claims = {"iss": ISSUER, "sub": "123", **patch}
                status, headers, _ = self.access(claims)
                self.assertEqual(status, 401)
                self.assertEqual(headers, {})

    def test_renderer_preserves_yaml_special_characters(self):
        secret = 'a' * 32 + '\\"\n:#${JWT_SECRET_JSON}$&'
        config = self.render(secret, "http://localhost:5173, https://app.example.com")
        self.assertEqual(config["consumers"][0]["jwt_secrets"][0]["secret"], secret)
        cors = next(p["config"] for p in config["plugins"] if p["name"] == "cors")
        self.assertEqual(cors["origins"], ["http://localhost:5173", "https://app.example.com"])
        self.assertFalse(cors["preflight_continue"])

    def test_renderer_rejects_missing_or_short_secrets_and_invalid_origins(self):
        for secret, origins in ((None, "http://localhost:5173"), ("short", "http://localhost:5173"),
                                ("a" * 32, "*"), ("a" * 32, "https://*.example.com"),
                                ("a" * 32, "https://example.com/path"), ("a" * 32, "")):
            with self.subTest(secret_length=len(secret or ""), origins=origins):
                with self.assertRaises(Exception):
                    self.render(secret, origins)

    def test_route_boundaries_and_authentication_configuration(self):
        config = self.render()
        routes = [route for service in config["services"] for route in service["routes"]]
        for route in routes:
            for path in route["paths"]:
                self.assertTrue(path.startswith("~/"), f"Invalid Kong regex path: {path}")

        def matches(route, path):
            return any(re.match(pattern[1:], path) for pattern in route["paths"])

        public = next(r for r in routes if r["name"] == "auth-public-routes")
        protected = [r for r in routes if r is not public]
        for path in ("/api/v1/auth/login", "/api/v1/auth/refresh/", "/health"):
            self.assertTrue(matches(public, path))
        for path in ("/api/v1/auth/login/admin", "/api/v1/auth/login-extra", "/health/private"):
            self.assertFalse(matches(public, path))
        auth = next(r for r in protected if r["name"] == "auth-protected-routes")
        self.assertTrue(matches(auth, "/api/v1/auth/login/admin"))
        self.assertGreater(public["regex_priority"], auth.get("regex_priority", 0))
        for route in protected:
            jwt = next(p["config"] for p in route["plugins"] if p["name"] == "jwt")
            self.assertIn("exp", jwt["claims_to_verify"])
            self.assertEqual(jwt["uri_param_names"], [])
            self.assertEqual(jwt["cookie_names"], [])
            self.assertTrue(any(p["name"] == "auth-perimeter" for p in route["plugins"]))
        menu = next(r for r in routes if r["name"] == "menu-routes")
        self.assertTrue(matches(menu, "/api/v1/menu/categories"))
        self.assertFalse(matches(menu, "/api/v1/menu-evil"))
        inventory = next(r for r in routes if r["name"] == "inventory-routes")
        self.assertTrue(inventory["strip_path"])
        remainder = re.sub(inventory["paths"][0][1:], "", "/api/v1/inventory/items")
        self.assertEqual("/" + remainder.lstrip("/"), "/items")

    def test_schema_defaults_and_public_override(self):
        lua = self.lua()
        lua.execute('''
          package.preload["kong.db.schema.typedefs"] = function()
            return { no_consumer = {}, protocols_http = {} }
          end
        ''')
        schema = lua.execute((ROOT / "plugins/auth-perimeter/schema.lua").read_text(encoding="utf-8"))
        fields = schema["fields"][3]["config"]["fields"]
        self.assertTrue(fields[1]["require_jwt"]["default"])
        self.assertEqual(fields[2]["issuer"]["default"], ISSUER)
        global_plugin = next(p for p in self.render()["plugins"] if p["name"] == "auth-perimeter")
        self.assertFalse(global_plugin["config"]["require_jwt"])

    def test_compose_keeps_admin_local_and_renders_required_secret(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        service = compose["services"]["kong"]
        self.assertIn("127.0.0.1:${KONG_ADMIN_PORT:-8001}:8001", service["ports"])
        self.assertTrue(service["environment"]["JWT_SECRET"].startswith("${JWT_SECRET:?"))
        self.assertTrue(any("config/render.lua:" in mount for mount in service["volumes"]))
        command = service["command"][-1]
        self.assertIn("umask 077", command)
        self.assertLess(command.index("resty"), command.index("exec /docker-entrypoint.sh"))
        self.assertEqual(service["environment"]["KONG_DECLARATIVE_CONFIG"], "/tmp/kong.yml")


if __name__ == "__main__":
    unittest.main()
