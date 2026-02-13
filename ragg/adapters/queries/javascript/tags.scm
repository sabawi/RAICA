; Function declarations
(function_declaration
  name: (identifier) @function_name
  parameters: (formal_parameters) @function_params
  body: (statement_block) @function_body
) @function_scope

; Class declarations
(class_declaration
  name: (identifier) @class_name
  body: (class_body) @class_body
) @class_scope

; Method definitions
(method_definition
  name: (property_identifier) @method_name
  parameters: (formal_parameters) @method_params
  body: (statement_block) @method_body
) @method_scope

; Function calls
(call_expression
  function: [
    (identifier) @call_function
    (member_expression
      property: (property_identifier) @call_method
    )
  ]
) @call_site
