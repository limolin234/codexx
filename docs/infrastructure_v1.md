# Infrastructure V1

This layer should be robust before more demos are added.

## Goals

- predictable failure behavior;
- durable event recording;
- SQLite performance sane defaults;
- clear transaction boundaries;
- replaceable in-process event bus;
- health checks for runtime components;
- no agent-specific business logic in infrastructure.

## Components

### SQLiteStore

Responsibilities:

- open SQLite with WAL;
- set busy timeout;
- enforce foreign keys;
- provide transaction context;
- expose narrow query helpers for module stores.

### Runtime event log

A durable append-only event table records important runtime facts:

- user input accepted;
- interactive emitted;
- main decided;
- audit result;
- task state changed;
- hook scheduled/fired;
- errors.

This is not the same as user-facing stream. It is infrastructure telemetry and recovery data.

### EventBus

First version is in-process and synchronous. It persists every event before dispatch. Later it can be replaced by async queues or IPC.

### Errors

Use typed runtime errors instead of raw generic exceptions where boundaries matter.

### Health

Health checks should be cheap, deterministic, and not call models by default.
