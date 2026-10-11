"""The notification center.

How a notification travels, one module per step:

1. ``notification_policies`` — "whenever X happens, raise notification Y".
   Each notification policy reacts to a domain event and builds a
   ``Notification`` through its named constructor.
2. ``service`` — ``raise_notification()`` stores it and queues its delivery in
   one transaction (transactional outbox).
3. ``dispatcher`` — the ``deliver_notification`` job: asks ``routing`` who
   hears this kind and on which channels, then hands it to each channel and
   logs the outcome.
4. ``channels`` — how a notification reaches people. Today only the inbox.
5. ``inbox`` — one person's inbox in one workspace, and its reading rules.
"""
