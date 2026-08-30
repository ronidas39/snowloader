Keeping a Copy in Step
======================

A delta sync asks one question and needs the answer to three. ``load_since``
returns rows whose ``sys_updated_on`` moved, which mixes newly created records
in with edited ones, and a deleted row leaves nothing behind for it to report.

A copy maintained that way gains records that no longer exist and never loses
them. Nothing warns, because from the outside a missing deletion looks exactly
like a quiet week.

.. contents::
   :local:
   :depth: 1


The short version
-----------------

.. code-block:: python

   from snowloader import SnowConnection

   with SnowConnection(...) as conn:
       report = conn.reconcile("incident", since=last_run)

   print(report)
   # table=incident since=2026-08-01 00:00:00 added=200 updated=1 deleted=597 complete=True

   for record in report.added:
       target.insert(record)
   for record in report.updated:
       target.update(record)
   for row in report.deleted:
       target.delete(row["sys_id"])

Or from a shell:

.. code-block:: bash

   snowloader reconcile incident --since 2026-08-01
   snowloader deleted cmdb_ci --since 2026-08-01 --out gone.csv


Where deletions actually live
-----------------------------

ServiceNow keeps one row per deleted record in ``sys_audit_delete``, carrying
the table it came from and its ``documentkey``, which is the ``sys_id``. The
record itself is gone, so the identifier is all that survives, and that is
enough to remove it from a copy.

Two things about that table decide whether a sync built on it is correct.


Deletions are filed against the real class
------------------------------------------

Sweeping ``cmdb_ci`` returns every subclass under it. The audit does not work
that way: deleting a Linux server files the deletion under
``cmdb_ci_linux_server``. Asking about the base table alone finds nothing at
all.

Measured on a developer instance:

.. code-block:: text

   tablename=cmdb_ci                  0 deletions
   the 711 class tables beneath it  895 deletions

So :meth:`~snowloader.SnowConnection.get_deleted_records` resolves descendants
before it asks, using ``sys_db_object.super_class``.

Matching on the name instead would be wrong in both directions. It would pull
in ``incident_task``, which is a separate table rather than a subclass of
``incident``, and it would miss ``incident`` entirely when resolving ``task``,
because the two share no prefix.

Turn it off with ``include_subclasses=False`` when you know the table has no
descendants and want to skip reading the table registry.


The audit does not go back forever
----------------------------------

``sys_audit_delete`` is pruned. A sync that runs less often than the instance
retains audit rows misses deletions permanently, and an empty result looks
identical to nothing having been deleted.

.. code-block:: python

   horizon = conn.get_deletion_horizon()
   # datetime(2026, 6, 12, 13, 58, 13, tzinfo=timezone.utc)

:attr:`ReconciliationReport.is_complete` is False when the cutoff predates that
point, and ``snowloader reconcile`` exits 1 for the same reason. Treat the
deleted list as a floor rather than the whole truth, and either sync more often
than the retention window or reconcile against a full sweep instead.


Added and updated are not the same thing
----------------------------------------

The split comes from comparing ``sys_created_on`` against the same cutoff, so
it costs nothing beyond a field on a sweep already being made.

A record created and deleted between two runs is reported only as deleted. It
never existed as far as the target is concerned, and reporting it as added as
well would have a sync write the row and then remove it.


A whole unattended sync
-----------------------

.. code-block:: python

   import logging
   from datetime import datetime, timezone
   from snowloader import SnowConnection

   with SnowConnection(...) as conn:
       report = conn.reconcile("cmdb_ci", since=last_run)

       if not report.is_complete:
           logging.error(
               "Deletions before %s are past the audit horizon on this "
               "instance, so this run cannot claim to be complete.",
               report.horizon,
           )
           raise SystemExit(1)

       apply_changes(report)
       record_watermark(datetime.now(timezone.utc))

Take the watermark from before the sweep started rather than after it
finished, or records changed while it ran are missed on the next pass.
