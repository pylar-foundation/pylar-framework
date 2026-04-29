# console/ — backlog

## ~~`make:*` extras~~ ✓

All five extensions landed:

* ~~`make:model --migration`~~ — prints follow-up `make:migration` command.
* ~~`make:controller --resource`~~ — scaffolds full REST surface
  (index/store/show/update/destroy) via `controller_resource.py.template`.
* ~~`make:listener --event ClassName`~~ — types the listener against a
  concrete event via `listener_typed.py.template`.
* ~~`make:policy --model ClassName`~~ — types the policy against a
  concrete model via `policy_typed.py.template`.
* ~~`make:factory --model ClassName`~~ — points the factory at the right
  `model_class` via `factory_typed.py.template`.

`pylar help <command>` and the typed :class:`Output` service landed:

* :class:`pylar.console.Output` exposes ``info`` / ``success`` /
  ``warn`` / ``error`` / ``write`` / ``line`` / ``table`` methods
  with optional ANSI colour (auto-detected from TTY). Commands
  receive it through their typed ``__init__``; the kernel binds a
  default singleton.
* :class:`BufferedOutput` is the test drop-in — captures into a
  StringIO with colour disabled by default.
* `pylar help <command>` prints the description and the input
  dataclass fields without running the command.
