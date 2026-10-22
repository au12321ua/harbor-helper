"""Alembic environment: always run with a connection supplied by maestro.db.migrate."""

from alembic import context

from maestro.db.schema import metadata

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
