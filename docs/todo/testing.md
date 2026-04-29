# testing/ — backlog

The Testing DX batch landed:

* the pytest plugin (registered through ``pytest11`` so installing
  pylar is enough — fixtures are auto-discovered: ``pylar_app_factory``,
  ``pylar_test_app``, ``assert_response``)
* the ``TestResponse`` HTTP assertion DSL with ``assert_status``,
  ``assert_ok`` / ``assert_unauthorized`` / ``assert_forbidden`` /
  ``assert_not_found`` / ``assert_unprocessable`` / ``assert_redirect``
  shortcuts, ``assert_header`` family, and the JSON helpers
  (``assert_json`` / ``assert_json_contains`` / ``assert_json_key`` /
  ``assert_json_count``)
* test fakes for the dispatcher-style services:
  ``Dispatcher.fake()`` (queue), ``Mailer.fake()``, ``EventBus.fake()``,
  ``NotificationDispatcher.fake()`` — drop-in for the real classes,
  recording every call with ``assert_*`` and ``sent`` / ``dispatched``
  inspection helpers.

What is still on the wishlist:

The testing-DX polish landed:

* :func:`bootstrap_schema(manager)` runs ``Model.metadata.create_all``
  against an existing :class:`ConnectionManager`.
* :func:`in_memory_manager` async-context manager: spins up a fresh
  in-memory aiosqlite manager, runs the schema bootstrap, disposes
  on exit.
* ``pylar_db_manager`` and ``pylar_db_session`` pytest fixtures
  (auto-discovered through the ``pytest11`` plugin) for the common
  "engine + ambient transactional session" pattern.
* :class:`Sequence`, :attr:`Factory.traits` + ``with_trait``,
  ``make_many`` / ``create_many`` for fan-out tests.

## Faker integration

`Factory.definition` is still hand-written. A first-class `faker`
helper that produces names, emails, dates, and addresses would cut
the boilerplate. Lives behind a `pylar[testing-faker]` extra so the
core install stays slim.
