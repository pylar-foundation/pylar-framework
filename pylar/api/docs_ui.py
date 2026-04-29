"""Static HTML for the Swagger UI and ReDoc viewers.

Both viewers are loaded from a CDN so pylar ships no bundled assets and
no build pipeline. The HTML is tiny (< 2 KB each) and identical to the
templates upstream vendors recommend.
"""

from __future__ import annotations

_SWAGGER_UI = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {{
      window.ui = SwaggerUIBundle({{
        url: "{spec_url}",
        dom_id: "#swagger-ui",
        deepLinking: true,
      }});
    }};
  </script>
</body>
</html>
"""

_REDOC = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
  <redoc spec-url="{spec_url}"></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


def swagger_ui_html(*, title: str = "API Docs", spec_url: str = "/openapi.json") -> str:
    return _SWAGGER_UI.format(title=title, spec_url=spec_url)


def redoc_html(*, title: str = "API Docs", spec_url: str = "/openapi.json") -> str:
    return _REDOC.format(title=title, spec_url=spec_url)
