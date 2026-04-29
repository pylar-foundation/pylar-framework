# notifications/ — backlog

## DatabaseChannel

A built-in channel that persists notifications into a `notifications`
table for in-app notification feeds. Pairs with a migration shipped by
`NotificationServiceProvider`. Notifications opt in via
`to_array(notifiable) -> dict`.

## BroadcastChannel

WebSocket-driven realtime delivery. Depends on the future `broadcasting/`
module landing first. Notifications opt in via
`to_broadcast(notifiable) -> dict`.

## SlackChannel and other webhooks

`SlackChannel`, `DiscordChannel`, generic `WebhookChannel`. Each lives
behind a `pylar[notifications-*]` extra so the base install stays slim.

## Queueable notifications

`Notification.should_queue = True` opts a notification into queue
dispatch via a generic `DeliverNotificationJob`. The notification
implements `to_payload(notifiable)` and `from_payload(container,
payload)` to round-trip the recipient + content across the worker
boundary.

## Targeted on-demand routes

`Notification::route("mail", "ad-hoc@example.com")` for one-off sends to
addresses that are not attached to a Notifiable model. Useful for system
alerts to operators.

## Locale per recipient

`Notification.locale(notifiable) -> str` so the same notification class
can render itself in the recipient's preferred language once the i18n
layer lands.

## Test fakes

`dispatcher.fake()` swaps in a recording dispatcher and exposes
`assert_sent(NotificationType, lambda n: n.user_id == 1)` for tests.
