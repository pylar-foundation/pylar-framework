# validation/ — backlog

`HeaderDTO`, `CookieDTO`, and a re-exported `UploadFile` landed
alongside `RequestDTO`. The router auto-resolver scans handler
parameters for any of the four types and feeds each one from the
right slice of the request (body/query, headers, cookies, multipart
form). Validation failures across all four paths render through the
same 422 exception.

## ~~Custom error renderers~~ ✓

`ValidationErrorRenderer` Protocol + `DefaultValidationRenderer`
landed. The routing compiler resolves the renderer from the container;
falls back to the default if none is bound. Teams that want RFC 7807
problem-details bind their own implementation in a service provider.

## ~~DTO autogeneration from Model~~ ✓

`model_dto(Model, exclude=[...], include=[...])` landed. Introspects
Model columns via SQLAlchemy inspection, maps SA types to Python types,
handles nullable/default fields as Optional, excludes PKs by default.
Returns a dynamic `RequestDTO` subclass compatible with the router's
auto-resolver.
