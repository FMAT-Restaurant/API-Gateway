local kong = kong
local jwt_parser = require "kong.plugins.jwt.jwt_parser"

local AuthPerimeterHandler = {
  PRIORITY = 900,
  VERSION = "1.1.0",
}

local function invalid_claims()
  return kong.response.exit(401, { message = "Invalid identity claims" })
end

local function safe_value(value)
  return type(value) == "string" and value ~= "" and not value:find("[%c,]")
end

local function valid_list(values)
  if type(values) ~= "table" then return false end
  local count = 0
  for key, value in pairs(values) do
    if type(key) ~= "number" or key < 1 or key % 1 ~= 0 or not safe_value(value) then
      return false
    end
    count = count + 1
  end
  return count == #values
end

function AuthPerimeterHandler:access(conf)
  kong.service.request.clear_header("X-User-Id")
  kong.service.request.clear_header("X-Staff-Id")
  kong.service.request.clear_header("X-User-Roles")
  kong.service.request.clear_header("X-User-Permissions")

  -- The global instance only sanitizes public requests. Protected routes override it.
  if not conf.require_jwt then
    return
  end

  local token = kong.ctx.shared.authenticated_jwt_token
  if type(token) ~= "string" or not kong.client.get_credential() then
    return kong.response.exit(401, { message = "Unauthorized" })
  end
  -- Kong 3.4 shares an encoded token after verification, not a claims table.
  local jwt = jwt_parser:new(token)
  if not jwt or type(jwt.claims) ~= "table" then return invalid_claims() end
  local jwt_claims = jwt.claims
  if jwt_claims.iss ~= conf.issuer or not safe_value(jwt_claims.sub) then
    return invalid_claims()
  end
  if jwt_claims.mustChangePassword ~= nil and type(jwt_claims.mustChangePassword) ~= "boolean" then
    return invalid_claims()
  end
  local staff_id = jwt_claims.staffId
  local numeric_staff_id = type(staff_id) == "number" and staff_id == math.floor(staff_id)
                          and staff_id > -math.huge and staff_id < math.huge
  if staff_id ~= nil and not safe_value(staff_id) and not numeric_staff_id then
    return invalid_claims()
  end
  for _, name in ipairs({ "roles", "permissions" }) do
    if jwt_claims[name] ~= nil and not valid_list(jwt_claims[name]) then
      return invalid_claims()
    end
  end

  local path = kong.request.get_path():gsub("/$", "")
  local method = kong.request.get_method()

  if jwt_claims.mustChangePassword == true then
    local is_allowed = (path == "/api/v1/auth/change-initial-password" and method == "POST")
                    or (path == "/api/v1/auth/logout" and method == "POST")
                    or (path == "/api/v1/auth/me" and method == "GET")

    if not is_allowed then
      return kong.response.exit(403, {
        code = "PASSWORD_CHANGE_REQUIRED",
        message = "Debe cambiar su contraseña temporal antes de acceder a servicios operativos."
      }, { ["Content-Type"] = "application/json" })
    end
  end

  if jwt_claims.sub then
    kong.service.request.set_header("X-User-Id", tostring(jwt_claims.sub))
  end

  if jwt_claims.staffId then
    kong.service.request.set_header("X-Staff-Id", tostring(jwt_claims.staffId))
  end

  if jwt_claims.roles and type(jwt_claims.roles) == "table" then
    kong.service.request.set_header("X-User-Roles", table.concat(jwt_claims.roles, ","))
  end

  if jwt_claims.permissions and type(jwt_claims.permissions) == "table" then
    kong.service.request.set_header("X-User-Permissions", table.concat(jwt_claims.permissions, ","))
  end
end

return AuthPerimeterHandler
