"""The :class:`Generator` — turns a template + name into a written file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template

from pylar.console.make.exceptions import TargetExistsError
from pylar.console.make.naming import to_kebab, to_snake, validate_pascal

#: The directory bundled with pylar that holds every ``*.py.template`` file.
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class GeneratorSpec:
    """A static description of one ``make:`` target.

    ``template`` is a filename inside :data:`TEMPLATE_DIR`. ``target`` is a
    path relative to the project base, written using ``string.Template``
    syntax so the generator can substitute the snake-case form of the
    user-supplied class name.
    """

    template: str
    target: str
    description: str


class Generator:
    """Render *spec*'s template against *name* and write it to disk.

    The generator validates that the supplied name is a PascalCase
    identifier, refuses to overwrite an existing file unless ``force`` is
    set, and creates any missing parent directories so the user does not
    have to scaffold the layout by hand.
    """

    def __init__(
        self,
        spec: GeneratorSpec,
        base_path: Path,
        name: str,
        *,
        force: bool = False,
        extra_class: str = "",
    ) -> None:
        self._spec = spec
        self._base_path = base_path
        self._name = validate_pascal(name)
        self._force = force
        self._extra_class = extra_class

    @property
    def target_path(self) -> Path:
        snake = to_snake(self._name)
        rendered = Template(self._spec.target).substitute(snake_name=snake)
        return self._base_path / rendered

    def render(self) -> str:
        template_path = TEMPLATE_DIR / self._spec.template
        template = Template(template_path.read_text(encoding="utf-8"))
        return template.substitute(self._substitutions())

    def write(self) -> Path:
        target = self.target_path
        if target.exists() and not self._force:
            raise TargetExistsError(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.render(), encoding="utf-8")
        return target

    def _substitutions(self) -> dict[str, str]:
        subs: dict[str, str] = {
            "class_name": self._name,
            "snake_name": to_snake(self._name),
            "kebab_name": to_kebab(self._name),
        }
        if self._extra_class:
            subs["extra_class"] = self._extra_class
            subs["extra_snake"] = to_snake(self._extra_class)
        return subs
