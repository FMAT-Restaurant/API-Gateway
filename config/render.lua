-- Run with the OpenResty interpreter bundled with Kong; no Perl dependency.
local json = require "cjson.safe"

local secret = assert(os.getenv("JWT_SECRET"), "JWT_SECRET is required")
assert(#secret >= 32, "JWT_SECRET must contain at least 32 bytes")
local origins = {}
for origin in (os.getenv("CORS_ORIGINS") or ""):gmatch("[^,]+") do
  origin = origin:match("^%s*(.-)%s*$")
  -- Kong treats origins containing regex metacharacters as regular expressions.
  assert(origin:match("^https?://[%w%.:%-]+$"),
         "CORS_ORIGINS must contain explicit http(s) origins without paths")
  origins[#origins + 1] = origin
end
assert(#origins > 0, "CORS_ORIGINS is required")

local input = assert(io.open("/usr/local/kong/declarative/kong.yml.template", "r"))
local template = input:read("*a")
input:close()
local values = {
  JWT_SECRET_JSON = assert(json.encode(secret)),
  CORS_ORIGINS_JSON = assert(json.encode(origins)),
  AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL") or "http://auth-backend:3000",
  MENU_SERVICE_URL = os.getenv("MENU_SERVICE_URL") or "http://menu-backend:8080",
  INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL") or "http://inventory-backend:3000",
  ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL") or "http://orders-backend:8082",
  KITCHEN_SERVICE_URL = os.getenv("KITCHEN_SERVICE_URL") or "http://kitchen-backend:8086",
  PAYMENTS_SERVICE_URL = os.getenv("PAYMENTS_SERVICE_URL") or "http://payments-backend:8084",
  FLOOR_SERVICE_URL = os.getenv("FLOOR_SERVICE_URL") or "http://floor-backend:8085",
}
local rendered = template:gsub("%${([%w_]+)}", function(key)
  return assert(values[key], "Unknown template variable: " .. key)
end)
local output = assert(io.open("/tmp/kong.yml", "w"))
assert(output:write(rendered))
assert(output:close())
