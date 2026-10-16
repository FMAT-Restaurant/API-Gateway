local kong = kong

local AuthPerimeterHandler = {
  PRIORITY = 900,
  VERSION = "1.0.0",
}

function AuthPerimeterHandler:access(conf)
  kong.service.request.clear_header("X-User-Id")
  kong.service.request.clear_header("X-Staff-Id")
  kong.service.request.clear_header("X-User-Roles")
  kong.service.request.clear_header("X-User-Permissions")

  local jwt_claims = kong.ctx.shared.authenticated_jwt_token
  if not jwt_claims then
    return
  end

  local path = kong.request.get_path()
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
