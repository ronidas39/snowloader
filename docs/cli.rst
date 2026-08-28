Command Line
============

Everything the library does correctly can also be done from a shell, without
writing a script around it.

.. contents::
   :local:
   :depth: 1


Why this exists
---------------

The library has had correct ordering, verification, resume and a partial
failure policy for some time. The command exists because people were still
assembling those by hand and getting it wrong quietly.

Of the extraction scripts written against this package before it existed, two
built their own encoded query with a non-unique sort, which meant they never
picked up the ordering fix at all, and one checked itself by comparing a line
count against the record count, which is the single check that cannot detect
the loss that causes.

So the defaults here are the careful ones. The sort always ends on a unique
key and there is no option to change that. Verification is on unless it is
switched off deliberately. An incomplete sweep exits non-zero, because
whatever runs next has no other way to find out.


Credentials
-----------

Read from the environment when the matching option is not given, so a password
need not appear in a shell history or a process list:

.. code-block:: bash

   export SNOW_INSTANCE=https://yourcompany.service-now.com
   export SNOW_USER=api_user
   export SNOW_PASS=...

``--instance``, ``--user`` and ``--password`` override them.


count
-----

How many records match, without fetching any:

.. code-block:: bash

   snowloader count incident
   snowloader count incident --query "stateIN6,7^close_notesISNOTEMPTY"

It prints a single number, so it composes:

.. code-block:: bash

   test "$(snowloader count incident --query active=true)" -gt 0 || exit 1


extract
-------

Write matching records to JSONL, one object per line:

.. code-block:: bash

   snowloader extract incident --out incidents.jsonl \
       --query "stateIN6,7^close_notesISNOTEMPTY" \
       --fields sys_id,number,close_notes,state \
       --display-value all

``--display-value all`` keeps both halves of every field, which is what you
want if the output is going into a graph rather than an index.

Faster, using the threaded paginator:

.. code-block:: bash

   snowloader extract cmdb_ci --out cmdb.jsonl --workers 16

Resumable, for anything long enough to be interrupted:

.. code-block:: bash

   snowloader extract incident --out incidents.jsonl --resume

Progress goes in ``incidents.jsonl.state.json`` beside the output. Run it,
kill it, run the same command again and it continues. A run that finishes
deletes its own state.


What it refuses to do
---------------------

**Overwrite an output file.** Truncating a finished extraction that took
twenty minutes would be an expensive surprise, so it stops and tells you to
pass ``--overwrite``.

**Resume onto a finished output.** A completed run deletes its state file, so
an output with no state beside it is finished. Appending to it would write the
whole table in a second time, and the result would look perfectly plausible
while holding every record twice. That is refused too.

**Sort on anything that is not unique.** Whatever you pass as ``--query``, the
ordering sent to the instance ends on ``sys_id``. This is the failure the
command was written to make unreachable.


Exit codes
----------

======  =========================================================
Code    Meaning
======  =========================================================
0       Finished, and verified unless ``--no-verify`` was passed
1       The sweep did not return every record
2       A usage or credential problem, or a refusal above
130     Interrupted. Re-run with ``--resume`` to continue
======  =========================================================

So an unattended job can simply check the status:

.. code-block:: bash

   snowloader extract incident --out incidents.jsonl --resume \
     || { echo "extraction incomplete" >&2; exit 1; }


Options
-------

======================== ==================================================
``--query``              Encoded query. The ordering is added for you
``--fields``             Comma separated. Every field by default
``--display-value``      ``true``, ``false`` or ``all``
``--page-size``          Records per request. Default 100
``--workers N``          Fetch pages with N threads. Sequential by default
``--resume``             Continue a previous run, and record this one
``--no-verify``          Skip the completeness check
``--skip-failed-pages``  Carry on past a dead page, and report it at the end
``--overwrite``          Replace the output file
``--quiet``              Warnings and errors only
======================== ==================================================
