"""Repro: the gql integration adds an event processor to the isolation scope on
every Client.execute() and never removes it.

Outside a per-request isolation scope (a script, a worker, a Celery task loop)
the processors pile up, and every later event, including unrelated errors,
gets the GraphQL request data of past queries. Also checks the response
context's "type" field."""

import json

import responses
import sentry_sdk
from gql import Client, gql
from gql.transport.exceptions import TransportQueryError
from gql.transport.requests import RequestsHTTPTransport
from sentry_sdk.integrations.gql import GQLIntegration
from sentry_sdk.transport import Transport

URL = "http://example.com/graphql"
events = []


class CaptureTransport(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                events.append(json.loads(item.payload.get_bytes()))


sentry_sdk.init(
    dsn="https://public@example.com/1",
    transport=CaptureTransport,
    integrations=[GQLIntegration()],
    send_default_pii=True,
)

client = Client(transport=RequestsHTTPTransport(url=URL))
scope = sentry_sdk.get_isolation_scope()


@responses.activate
def run_query(text, response_json):
    responses.add(responses.POST, URL, json=response_json, status=200)
    return client.execute(gql(text))


before = len(scope._event_processors)
for i in range(100):
    run_query("query Q%d { example }" % i, {"data": {"example": i}})
after = len(scope._event_processors)
print("processors on the isolation scope: before=%d after 100 successful queries=%d" % (before, after))

# An unrelated error, long after the last query finished.
try:
    raise ValueError("unrelated error")
except ValueError:
    sentry_sdk.capture_exception()
sentry_sdk.flush()

unrelated = events[-1]
print("unrelated event exception:", unrelated["exception"]["values"][0]["value"])
print("unrelated event request:", json.dumps(unrelated.get("request")))
print("unrelated event contexts.response:", json.dumps(unrelated.get("contexts", {}).get("response")))

# A real gql error, to see the response context it produces.
try:
    run_query("query Bad { example }", {"errors": [{"message": "boom"}]})
except TransportQueryError:
    pass
sentry_sdk.flush()
gql_event = events[-1]
print("gql error contexts.response:", json.dumps(gql_event.get("contexts", {}).get("response")))
print("processors after the failing query:", len(scope._event_processors))

ok_pile_up = after - before == 100
ok_leak = (unrelated.get("request") or {}).get("api_target") == "graphql"
print("RESULT processors_pile_up=%s unrelated_event_tagged_as_graphql=%s" % (ok_pile_up, ok_leak))
