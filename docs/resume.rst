Resuming a Long Extraction
==========================

A sweep of half a million records takes long enough that something will
eventually interrupt one. A dropped connection, a restarted container, a
laptop lid. Starting again from zero throws away the part that already
worked.

A checkpoint writes down where a run had reached, so running the same call
again continues from there.

.. contents::
   :local:
   :depth: 1


The shortest version
--------------------

.. code-block:: python

   import json
   from snowloader import FileCheckpoint, SnowConnection

   checkpoint = FileCheckpoint("cmdb_sweep.json")

   with SnowConnection(...) as conn, open("cmdb.jsonl", "a") as out:
       for record in conn.get_records("cmdb_ci", keyset=True, checkpoint=checkpoint):
           out.write(json.dumps(record) + "\n")

Run it, kill it, run it again. The second run picks up where the first
stopped. A run that reaches the end deletes its own state file, so the next
one starts clean rather than resuming a finished job.


Two paths, two kinds of position
--------------------------------

**Keyset**, on :meth:`SnowConnection.get_records`, remembers one value: the
``sys_id`` of the last record of the last completed page. It is exact, it is
small, and it still means the same thing tomorrow, because it names an actual
record rather than a position in a list.

This path requires ``keyset=True``. Plain offset paging is refused here, and
the reason is worth stating: an offset only means something while the result
set stays in the same order, which is not something a later run can rely on.

**Threaded**, on :meth:`SnowConnection.concurrent_get_records`, remembers the
set of page offsets that finished. That path completes pages out of order, so
a single furthest offset would describe nothing useful. It records each offset
only once every record of that page has been handed over.

.. code-block:: python

   records = conn.concurrent_get_records(
       "incident",
       max_workers=16,
       checkpoint=FileCheckpoint("incident_sweep.json"),
   )


It repeats rather than drops
----------------------------

State is written when a page is complete, not when a record is handed over.
An interrupted run therefore resumes at a page boundary and re-delivers the
page it was in the middle of.

That is deliberate. Repeating a page costs you some duplicates, which you can
remove by ``sys_id``. Skipping one costs you records, and you would not know
which. Measured on a developer instance, interrupting a sweep of 2,919 records
after 500 with a page size of 200:

.. code-block:: text

   run 1  wrote 500, interrupted
   run 2  wrote 2519, completed

   total lines 3019   distinct 2919   api count 2919
   missing 0          duplicates 100

The 100 duplicates are the interrupted page. Nothing was lost.

If your output must be unique, deduplicate on ``sys_id`` as you write, or
sweep once more at the end with ``verify=True``.


A checkpoint will not resume the wrong thing
--------------------------------------------

A state file is just a file, and nothing about it says which extraction it
belongs to. Read one back against a different table or filter and the output
becomes partly one thing and partly another, with nothing to show for it.

So every checkpoint carries a fingerprint of the run that wrote it: table,
query including its ordering, field list, page size and mode. A run whose
fingerprint does not match is refused:

.. code-block:: text

   SnowConnectionError: The checkpoint at cmdb_sweep.json belongs to a
   different extraction. Table, query, field list or page size has changed
   since it was written. Resuming would mix two different result sets into
   one output. Delete the file to start again, or point this run at its own
   checkpoint.

Page size is in the fingerprint because it changes where the page boundaries
fall, so a recorded offset no longer refers to the same records.

Give each extraction its own checkpoint file. Two pulls that share one will
refuse to run rather than corrupt each other.


Keeping the state somewhere else
--------------------------------

:class:`~snowloader.FileCheckpoint` writes JSON next to your output, and its
writes are atomic: state goes to a temporary file and is then moved into
place, so a process killed mid-write leaves either the old state or the new
one, never half of either. A file it cannot parse is treated as absent rather
than fatal, so a hard kill during a write cannot block the next run.

When several machines need to see the same run, implement
:class:`~snowloader.Checkpoint` over whatever they share:

.. code-block:: python

   class RedisCheckpoint:
       def __init__(self, client, key):
           self._client, self._key = client, key

       def load(self, fingerprint):
           raw = self._client.get(self._key)
           if raw is None:
               return None
           payload = json.loads(raw)
           if payload["fingerprint"] != fingerprint:
               raise SnowConnectionError("checkpoint is for a different extraction")
           return payload["state"]

       def save(self, fingerprint, state):
           self._client.set(self._key, json.dumps(
               {"fingerprint": fingerprint, "state": state}))

       def clear(self):
           self._client.delete(self._key)

Raising on a fingerprint mismatch is the part not to skip. It is the check
that stops two different extractions being stitched into one file.


A whole unattended run
----------------------

.. code-block:: python

   import json
   from snowloader import FileCheckpoint, SnowConnection, SweepIncompleteError

   checkpoint = FileCheckpoint("cmdb_sweep.json")

   with SnowConnection(
       instance_url="https://yourcompany.service-now.com",
       username="api_user",
       password="api_pass",
       page_size=100,
   ) as conn:
       try:
           with open("cmdb.jsonl", "a") as out:
               for record in conn.get_records(
                   "cmdb_ci",
                   keyset=True,
                   checkpoint=checkpoint,
                   verify=True,
               ):
                   out.write(json.dumps(record) + "\n")
       except SweepIncompleteError as exc:
           alert(f"CMDB extract incomplete: {exc.report}")
           raise

Killed at any point, it restarts where it stopped. Finished, it clears its own
state and has proved it returned everything.
