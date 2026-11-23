local typedefs = require "kong.db.schema.typedefs"

return {
  name = "auth-perimeter",
  fields = {
    { consumer = typedefs.no_consumer },
    { protocols = typedefs.protocols_http },
    {
      config = {
        type = "record",
        fields = {
          { require_jwt = { type = "boolean", required = true, default = true } },
          { issuer = { type = "string", required = true, default = "urn:fmat:restaurant:auth" } },
          -- Claim "aud" que deben traer los tokens (debe coincidir con JWT_AUDIENCE de Auth-Backend).
          { audience = { type = "string", required = true, default = "urn:fmat:restaurant" } },
        },
      },
    },
  },
}
