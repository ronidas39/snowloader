API Reference
=============

This section is auto-generated from the source code docstrings.

Connection
----------

.. autoclass:: snowloader.SnowConnection
   :members:
   :special-members: __init__, __enter__, __exit__

.. autoclass:: snowloader.SnowConnectionError
   :members:
   :special-members: __init__

.. autoclass:: snowloader.SweepIncompleteError
   :members:
   :special-members: __init__
   :show-inheritance:

Checkpoints
-----------

.. autoclass:: snowloader.Checkpoint
   :members:

.. autoclass:: snowloader.FileCheckpoint
   :members:
   :special-members: __init__

.. autofunction:: snowloader.checkpoints.fingerprint

Sweep Verification
------------------

.. autoclass:: snowloader.SweepReport
   :members:

.. autoclass:: snowloader.sweep.SweepTracker
   :members:

Ordering
--------

.. automodule:: snowloader.ordering
   :members:

Field Helpers
-------------

.. autoclass:: snowloader.ReferenceField
   :members:

.. autofunction:: snowloader.reference

.. autofunction:: snowloader.display_value

.. autofunction:: snowloader.raw_value

.. autofunction:: snowloader.is_sys_id

.. autofunction:: snowloader.parse_boolean

.. autofunction:: snowloader.expand_reference_keys

.. autofunction:: snowloader.parse_labelled_int

Models
------

.. autoclass:: snowloader.SnowDocument
   :members:

.. autoclass:: snowloader.BaseSnowLoader
   :members:

Loaders
-------

.. autoclass:: snowloader.IncidentLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.KnowledgeBaseLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.CMDBLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.ChangeLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.ProblemLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.CatalogLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.AttachmentLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.RelationshipLoader
   :members:
   :show-inheritance:

.. autoclass:: snowloader.TableLoader
   :members:
   :show-inheritance:

HTML Cleaner
~~~~~~~~~~~~

.. automodule:: snowloader.utils.html_cleaner
   :members:
