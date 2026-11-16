# Migrations explained (simple version)

## 1. What is a migration?

Your database has tables (`users`, `sessions`, ...). Over time the tables change: you add a table, add a column, add an index.

A **migration** is a small Python file that describes **one such change**, written as code. Instead of opening the database and clicking or typing SQL by hand, you write the change in a file and a tool runs it for you.

Think of it as a **logbook of changes to the database structure**. Each page says "on this step, create the `users` table".

Example from this project: `versions/0003_create_sessions.py` creates the `sessions` table.

## 2. Why do we use it?

- **Everyone gets the same database.** Your laptop, your teammate's laptop, the test server and production all end up with identical tables, by running the same files.
- **Changes are tracked in git.** You can see who changed the database, when, and why.
- **Safe and repeatable.** You never forget "what did I change by hand last week?".
- **A fresh database can be built from nothing.** Run all migrations on an empty database and you get the full structure. Docker does this automatically: the `api` container runs `alembic upgrade head` every time it starts.
- **Can be undone.** Each migration also says how to reverse itself.

## 3. Alembic: the tool that runs them

**Alembic** is the migration tool this project uses (the name is often mistyped as "ambleyic"). It does three jobs:

1. Keeps the migration files in order.
2. Remembers which ones the database has already had, so it only runs the new ones.
3. Runs them with a command.

Commands you will use:

| Command | Meaning |
|---|---|
| `alembic upgrade head` | Apply every migration that has not been applied yet |
| `alembic downgrade -1` | Undo the last migration |
| `alembic current` | Which migration is the database on now? |
| `alembic history` | List all migrations in order |
| `alembic revision -m "add something"` | Create a new, empty migration file |

## 4. How is this different from "just changing the table by hand"?

| By hand (SQL in a tool) | Migrations |
|---|---|
| Nobody knows what changed | Every change is a file in git |
| Your database and a teammate's drift apart | Everyone runs the same files |
| Hard to rebuild from scratch | One command builds everything |
| No undo | `downgrade` is written next to `upgrade` |

It is also different from `create_all()` (a SQLAlchemy shortcut that creates tables from your models). `create_all()` only creates **missing tables**. It cannot change an existing table or move data. Migrations can, which is why real projects use them.

## 5. What is in this folder?

```
migrations/
├── env.py            # the "connection setup" for Alembic (section 7)
├── script.py.mako    # template used when creating a new migration file
├── versions/         # the migration files themselves (section 6)
│   ├── 0001_enable_pgvector.py
│   ├── 0002_create_users.py
│   └── 0003_create_sessions.py
└── migrations.md     # this file
```

Also, `BD_BACKEND/alembic.ini` is the settings file. Its main job here is `script_location = migrations`, which tells Alembic where this folder is.

## 6. Why do we need the `versions/` folder?

It holds **one file per change**, and the files are chained in order. This is the history.

Each file has two important names:

```python
revision = "0003"          # this file's ID
down_revision = "0002"     # the file that must run before this one
```

So the chain is: `0001` -> `0002` -> `0003`.

Each file has two functions:

- `upgrade()` does the change, for example `op.create_table("sessions", ...)`.
- `downgrade()` reverses it, for example `op.drop_table("sessions")`.

The database keeps a tiny table called `alembic_version` that stores just one value: the ID of the last migration applied. Alembic compares that with the chain in `versions/` and runs only what is missing.

Why separate files instead of one big file? Because production already has `0001` to `0003`. When you add `0004`, only `0004` runs. If it were one big file, you couldn't tell what is new.

## 7. Why do we need `env.py`? Is it related to Alembic?

Yes. `env.py` is **part of Alembic**. It is created by `alembic init` and Alembic runs it every time you use a command like `upgrade`.

Alembic on its own doesn't know two things:

1. **Which database to connect to.**
2. **What your models look like** (needed to auto-generate migrations).

`env.py` answers both. In this project it does this:

- It reads the database address from `app.config` (the same `DATABASE_URL` the app uses). So migrations always run against the same database as the app. Tests can override it.
- It imports `app.core.models` and uses `Base.metadata`. That is the list of all your model tables, which lets Alembic compare "what the code says" with "what the database has".
- It has two modes:
  - **Online** (normal): connect and run the changes.
  - **Offline**: only print the SQL, without connecting (`alembic upgrade head --sql`).

So: `alembic.ini` says where things are, `env.py` says how to connect, and `versions/` holds the changes.

## 8. What happens when the API container starts?

```
alembic upgrade head
  -> reads alembic.ini, finds migrations/
  -> runs env.py (connects to the database)
  -> checks alembic_version table, say it says 0002
  -> runs 0003 only
  -> alembic_version now says 0003
then uvicorn starts the API
```

Running it twice is harmless: the second time nothing is missing, so nothing happens.

## 9. Golden rules for this project

1. **Every model change needs a migration.** Changing `models.py` alone does not change the database.
2. **Never edit a migration that has already been applied.** Others (and production) already ran the old version. Make a **new** migration instead.
3. **Write a `downgrade()`**, and say in the docstring what risk the change has (for example, "downgrade deletes all sessions").
4. **Keep each migration small:** one clear change per file.
5. **Check it works on an empty database.** That is part of the project's "done" checklist.
6. **Dangerous changes go in steps** (add the new thing, move the data, then remove the old thing), never all at once.

## 10. Quick example: adding a column

1. Add `phone` to the `User` model in `app/core/models.py`.
2. Run `alembic revision -m "add phone to users"`. This creates `versions/0004_add_phone_to_users.py` with `down_revision = "0003"`.
3. Fill in the functions:
   ```python
   def upgrade() -> None:
       op.add_column("users", sa.Column("phone", sa.String(), nullable=True))

   def downgrade() -> None:
       op.drop_column("users", "phone")
   ```
4. Run `alembic upgrade head`, then run the tests.
