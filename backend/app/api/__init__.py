"""HTTP layer: thin adapters that translate requests into application calls.

Route handlers contain no orchestration. If a handler is doing more than
validating input, calling one application service, and shaping the response,
the logic belongs in the application layer where it can be tested without HTTP.
"""
