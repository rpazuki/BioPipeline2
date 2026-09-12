"""Application layer: use cases and transaction boundaries.

Coordinates the domain layer and the infrastructure adapters. Services never
commit: the caller owns the transaction, so a route can compose several use
cases atomically and a test can roll everything back.
"""
