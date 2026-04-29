"""Foundation layer: Application, Container, ServiceProvider, lifecycle primitives."""

from pylar.foundation.application import AppConfig, Application
from pylar.foundation.binding import Binding, Concrete, Factory, Scope
from pylar.foundation.container import Container
from pylar.foundation.exceptions import (
    BindingError,
    CircularDependencyError,
    ContainerError,
    ResolutionError,
)
from pylar.foundation.kernel import Kernel
from pylar.foundation.plugins import PluginInfo, discover_providers, list_plugins
from pylar.foundation.provider import ServiceProvider

__all__ = [
    "AppConfig",
    "Application",
    "Binding",
    "BindingError",
    "CircularDependencyError",
    "Concrete",
    "Container",
    "ContainerError",
    "Factory",
    "Kernel",
    "PluginInfo",
    "ResolutionError",
    "Scope",
    "ServiceProvider",
    "discover_providers",
    "list_plugins",
]
