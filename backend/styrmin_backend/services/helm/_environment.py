from jinja2 import Environment, PackageLoader, select_autoescape


_jinja_environment = None


def get_jinja_environment() -> Environment:
    """Get the jinja environment for rendering Helm Repository specifications."""

    global _jinja_environment

    if _jinja_environment is None:
        _jinja_environment = Environment(
            loader=PackageLoader(__package__),
            autoescape=select_autoescape(),
        )

    return _jinja_environment
