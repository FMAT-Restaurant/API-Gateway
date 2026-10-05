local typedefs = require "kong.db.schema.typedefs"

return {
  name = "auth-perimeter",
  fields = {
    { consumer = typedefs.no_consumer },
    { protocols = typedefs.protocols_http },
    {
      config = {
        type = "record",
        fields = {},
      },
    },
  },
}
