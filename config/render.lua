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
}
local rendered = template:gsub("%${([%w_]+)}", function(key)
  return assert(values[key], "Unknown template variable: " .. key)
end)
local output = assert(io.open("/tmp/kong.yml", "w"))
assert(output:write(rendered))
assert(output:close())
