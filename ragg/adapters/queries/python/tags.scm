(function_definition
  name: (identifier) @function.name
  parameters: (parameters) @function.params
  body: (block) @function.body
) @function.scope

(class_definition
  name: (identifier) @class.name
  body: (block) @class.body
) @class.scope

(call
  function: [
    (identifier) @call.function
    (attribute
      object: (identifier) @call.object
      attribute: (identifier) @call.method
    )
  ]
) @call.site

(import_statement
  name: (dotted_name) @import.module
) @import.stmt

(import_from_statement
  module_name: (dotted_name) @import.from_module
  name: (dotted_name) @import.name
) @import.from_stmt
